"""Fail-closed viewer and exact-free preflight for Hanayume episodes."""

from __future__ import annotations

import asyncio
import base64
import binascii
import io
import re
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qsl, urlsplit

from PIL import Image, UnidentifiedImageError
from playwright.async_api import ElementHandle, Locator, Page, Request, Response
from playwright.async_api import Error as PlaywrightError

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
from screenshot_crawler.site_adapters.base import AccessConsumption, SiteAdapter
from screenshot_crawler.site_adapters.hanayume.access import hanayume_access_profile
from screenshot_crawler.site_adapters.hanayume.discovery import (
    MAX_EPISODE_ACCESS_SECONDS,
    RANGE_LABEL,
    RANGE_PAGE_SIZE,
    WAIT_AND_FREE_ACCESS_TYPE,
    HanayumeNativeEpisodeAccess,
    _latest_native_access_by_episode,
    _read_series_authentication,
    _SeriesAccessObserver,
    classify_hanayume_access,
    parse_hanayume_episode_url,
    parse_hanayume_work_url,
)
from screenshot_crawler.site_adapters.hanayume.native_capture import (
    COLLECT_CAPTURE_SCRIPT,
    OBSERVER_INIT_SCRIPT,
    RELEASE_CAPTURE_SCRIPT,
    VERIFY_CAPTURE_SCRIPT,
    decode_capture_images,
    encode_native_webp,
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
CAPTURE_BUDGET_SECONDS = 10.0
RANGE_PACING_MS = 350
VIEWER_COUNTER_READY_TIMEOUT_MS = 5_000
VIEWER_COUNTER_POLL_INTERVAL_MS = 100
INITIAL_CANVAS_QUIET_MS = 1_000
INITIAL_CANVAS_SETTLE_TIMEOUT_MS = 5_000
INITIAL_CANVAS_POLL_INTERVAL_MS = 100
MAX_RANGE_PAGES = 100
MAX_LISTING_ROWS = RANGE_PAGE_SIZE * MAX_RANGE_PAGES
INITIALIZE_TIMEOUT_MS = 240_000
MAX_PNG_BYTES = 8_000_000
POLL_INTERVAL_SECONDS = 0.15
TICKET_AUTH_READY_TIMEOUT_SECONDS = 8.0
TICKET_RECOVERY_WINDOW_SECONDS = 5.0
TICKET_POLL_INTERVAL_SECONDS = 0.1
TICKET_API_BODY_TIMEOUT_SECONDS = 2.0
TICKET_CONTROL_SELECTOR = (
    'div.ep-main-content.mode-charge > div.ep-charge > div.ep-charge-act '
    '> button[data-e2e="wfRead"]'
)
TICKET_CONTROL_LABEL = "待つと無料で読む"

TICKET_ENTRY_SNAPSHOT_SCRIPT = r"""(episodeId) => {
  const all = selector => [...document.querySelectorAll(selector)];
  const exact = selector => {
    const nodes = all(selector);
    return nodes.length === 1 ? nodes[0] : null;
  };
  const visible = node => {
    if (!node) return false;
    const style = getComputedStyle(node), rect = node.getBoundingClientRect();
    return style.display !== 'none' && style.visibility !== 'hidden' &&
      Number(style.opacity || '1') > 0 && rect.width > 0 && rect.height > 0;
  };
  const targetHref = `https://hanayume.com/episodes/${episodeId}`;
  const headerIds = all('#xHeader');
  const headers = all('#xHeader.ep-h');
  const header = exact('#xHeader.ep-h');
  const workLinks = all('#xHeader a.ep-h-main-h-series');
  const episodeMarkers = all('[data-e2e="pageEpisode"]');
  const episodePages = all('div.ep-main.series-safe-filter-target[data-e2e="pageEpisode"]');
  const page = exact('div.ep-main.series-safe-filter-target[data-e2e="pageEpisode"]');
  const episodeModes = page ? [...page.children].filter(node =>
    node.tagName === 'DIV' && node.classList.contains('series') &&
    node.classList.contains('mode-ep') && !node.hasAttribute('data-e2e')) : [];
  const episodeMode = episodeModes.length === 1 ? episodeModes[0] : null;
  const wrappers = page ? [...page.querySelectorAll('.series-eplist-wrap')] : [];
  const wrapper = wrappers.length === 1 ? wrappers[0] : null;
  const listMains = wrapper ? [...wrapper.children].filter(node =>
    node.classList.contains('series-eplist-main')) : [];
  const listMain = listMains.length === 1 ? listMains[0] : null;
  const roots = page ? [...page.querySelectorAll('.series-eplist[data-e2e="epListUser"]')] : [];
  const userRoot = roots.length === 1 ? roots[0] : null;
  const rootClasses = userRoot ? [...userRoot.classList].sort() : [];
  const loginAnchors = all('a').filter(anchor => {
    const href = anchor.getAttribute('href') || '';
    const label = (anchor.innerText || '').replace(/\s+/g, ' ').trim();
    return /login|signin|sign-in/i.test(href) || /ログイン|サインイン|login/i.test(label);
  });
  const overlays = all('dialog,[role="dialog"],.modal,.modal-backdrop').filter(visible);
  const publicRoots = page ? [...page.querySelectorAll('.series-eplist[data-e2e="epList"]')] : [];
  const publicRoot = publicRoots.length === 1 ? publicRoots[0] : null;
  const rowList = userRoot ? [...userRoot.querySelectorAll(
    '.series-eplist-item[data-e2e="eli"]')] : [];
  const publicRowList = publicRoot ? [...publicRoot.querySelectorAll(
    '.series-eplist-item[data-e2e="eli"]')] : [];
  const readRows = rows => rows.map(row => {
    const links = [...row.querySelectorAll('a.series-eplist-item-link')];
    const titles = [...row.querySelectorAll('[data-e2e="eliTitle"]')];
    const wfIcons = [...row.querySelectorAll('[data-e2e="eliWfIcon"]')];
    const ifIcons = [...row.querySelectorAll('[data-e2e="eliIfIcon"]')];
    const rentalStats = [...row.querySelectorAll('[data-e2e="eliRentStat"]')];
    return {
      hrefs: links.map(node => node.href),
      titleCount: titles.length,
      wfIconCount: wfIcons.length,
      ifIconCount: ifIcons.length,
      classes: [...row.classList].sort(),
      rentalStats: rentalStats.map(node =>
        (node.innerText || '').replace(/\s+/g, ' ').trim())
    };
  });
  const rows = readRows(rowList);
  const publicRows = readRows(publicRowList);
  const targetRows = rows.filter(row => row.hrefs.includes(targetHref));
  const publicTargetRows = publicRows.filter(row => row.hrefs.includes(targetHref));
  const currentRows = rows.filter(row => row.classes.includes('mode-current'));
  const rowsAreWellFormed = rows => rows.length > 0 &&
    new Set(rows.map(row => row.hrefs.length === 1 ? row.hrefs[0] : null)).size === rows.length &&
    rows.every(row => row.hrefs.length === 1 &&
      /^https:\/\/hanayume\.com\/episodes\/[0-9a-f]{13}$/.test(row.hrefs[0]) &&
      row.titleCount === 1);
  const controls = all('button[data-e2e="wfRead"]');
  const control = controls.length === 1 ? controls[0] : null;
  const label = control ? (control.innerText || '').replace(/\s+/g, ' ').trim() : '';
  const act = control?.closest('.ep-charge-act') ?? null;
  const charge = act?.parentElement ?? null;
  const chargeMain = charge?.parentElement ?? null;
  const chargeMains = all('div.ep-main-content.mode-charge');
  const rect = control?.getBoundingClientRect();
  const center = rect ? document.elementFromPoint(rect.left + rect.width / 2,
    rect.top + rect.height / 2) : null;
  const chargeStructure = !!control && !!act && !!charge && !!chargeMain &&
    chargeMains.length === 1 && chargeMain === chargeMains[0] &&
    act.parentElement === charge && charge.classList.contains('ep-charge') &&
    chargeMain.classList.contains('ep-main-content') &&
    chargeMain.classList.contains('mode-charge');
  let rootState = 'unknown';
  if (!userRoot) rootState = 'missing';
  else if (rootClasses.includes('mode-no-user')) rootState = 'no_user';
  else if (rootClasses.includes('mode-loading')) rootState = 'loading';
  else if (rootClasses.join(' ') === 'mode-has-eps mode-user series-eplist') rootState = 'ready';
  return {
    href: location.href,
    routeExact: location.origin === 'https://hanayume.com' &&
      location.pathname === `/episodes/${episodeId}` && !location.search && !location.hash,
    headerExact: headerIds.length === 1 && headers.length === 1 && !!header &&
      workLinks.length === 1 && workLinks[0].href.startsWith('https://hanayume.com/series/'),
    workHref: workLinks.length === 1 ? workLinks[0].href : null,
    episodePageExact: episodeMarkers.length === 1 && episodePages.length === 1 &&
      !!page && episodeModes.length === 1 && episodeMode?.parentElement === page &&
      wrappers.length === 1 && wrapper?.parentElement === episodeMode && listMains.length === 1 &&
      listMain?.parentElement === wrapper && roots.length === 1 &&
      userRoot?.parentElement === listMain,
    previewRootsExact: roots.length === 1 && publicRoots.length === 1 &&
      userRoot?.parentElement === listMain && publicRoot?.parentElement === listMain,
    publicRowsValid: rowsAreWellFormed(publicRows),
    accountRowsValid: rowsAreWellFormed(rows),
    publicRowCount: publicRows.length,
    accountRowCount: rows.length,
    rootState, rootClasses,
    loginVisible: loginAnchors.some(visible),
    overlayVisible: overlays.length > 0,
    targetRows,
    publicTargetRows,
    publicTargetLinkCount: publicTargetRows.reduce((sum, row) =>
      sum + row.hrefs.filter(href => href === targetHref).length, 0),
    accountTargetLinkCount: targetRows.reduce((sum, row) =>
      sum + row.hrefs.filter(href => href === targetHref).length, 0),
    accountOtherCurrentRowCount: currentRows.filter(row => !row.hrefs.includes(targetHref)).length,
    controlCount: controls.length,
    controlText: label,
    controlClasses: control ? [...control.classList].sort() : [],
    controlVisible: visible(control),
    controlEnabled: !!control && !control.disabled && control.getAttribute('aria-disabled') !== 'true',
    controlCovered: !!control && visible(control) && !(center && (center === control || control.contains(center))),
    chargeStructure,
    controlHasCost: !!control && ['data-price','data-cost','data-buy-price'].some(name =>
      control.hasAttribute(name)),
    controlHasInlineHandler: !!control && control.hasAttribute('onclick')
  };
}"""

SNAPSHOT_SCRIPT = r"""({includePng = false, stabilitySlots = []} = {}) => {
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
    canvasStability: stabilitySlots.length &&
      typeof window.__hanayumeNativeCapture?.stability === 'function'
      ? window.__hanayumeNativeCapture.stability(stabilitySlots) : null,
    slots
  };
}"""

VIEWER_COUNTER_READINESS_SCRIPT = r"""() => {
  const count = selector => document.querySelectorAll(selector).length;
  const current = [...document.querySelectorAll('.-cv-f-page-current')];
  const total = [...document.querySelectorAll('.-cv-f-page-total')];
  if (count('#comici-viewer') !== 1 || count('#xCVPages') !== 1 ||
      count('#xCVSeekBar') !== 1) return true;
  if (current.length > 1 || total.length > 1) return true;
  if (current.length !== 1 || total.length !== 1) return false;
  return (current[0].textContent || '').trim().length > 0 &&
    (total[0].textContent || '').trim().length > 0;
}"""

RANGE_SNAPSHOT_SCRIPT = r"""() => {
  const wrappers = [...document.querySelectorAll('.series-eplist-wrap')];
  const wrapper = wrappers.length === 1 ? wrappers[0] : null;
  const outer = wrapper?.parentElement ?? null;
  const routeOuterValid = outer?.tagName === 'DIV' &&
    outer.classList.contains('series') && outer.classList.contains('mode-series-top') &&
    outer.classList.contains('series-safe-filter-target') &&
    outer.dataset.e2e === 'pageSeries';
  const mains = wrapper ? [...wrapper.children].filter(node =>
    node.classList.contains('series-eplist-main')) : [];
  const main = mains.length === 1 ? mains[0] : null;
  const roots = wrapper ? [...wrapper.querySelectorAll('.series-eplist')] : [];
  const allRoots = [...document.querySelectorAll('.series-eplist')];
  const publicRoots = roots.filter(root => root.dataset.e2e === 'epList');
  const userRoots = roots.filter(root => root.dataset.e2e === 'epListUser');
  const rowsKnown = [...document.querySelectorAll('.series-eplist-item[data-e2e="eli"]')]
    .every(row => publicRoots[0]?.contains(row) || userRoots.some(root => root.contains(row)));
  const structureReady = wrappers.length === 1 && routeOuterValid &&
    allRoots.length === roots.length && mains.length === 1 &&
    main?.parentElement === wrapper && publicRoots.length === 1 &&
    publicRoots[0].parentElement === main && userRoots.length <= 1 &&
    roots.length === publicRoots.length + userRoots.length &&
    userRoots.every(root => root.parentElement === main && root.classList.contains('mode-user')) &&
    rowsKnown;
  const readRows = root => [...root.querySelectorAll(
    '.series-eplist-item[data-e2e="eli"]')].map((row, index) => {
      const links = [...row.querySelectorAll('a.series-eplist-item-link')];
      const badges = [...row.querySelectorAll('.series-eplist-item-access-text')];
      return {
        index,
        linkCount: links.length,
        href: links.length === 1 ? links[0].href : null,
        labels: badges.map(node => (node.innerText || '').replace(/\s+/g, ' ').trim())
      };
    });
  return {
    path: location.pathname,
    structureReady,
    ranges: wrapper ? [...wrapper.querySelectorAll('a.series-sort-link')].map(anchor => ({
      label: (anchor.innerText || '').replace(/\s+/g, ' ').trim(),
      href: anchor.href,
      current: anchor.classList.contains('mode-current')
    })) : [],
    rows: publicRoots.length === 1 ? readRows(publicRoots[0]) : [],
    historyRows: userRoots.length === 1 ? readRows(userRoots[0]) : []
  };
}"""


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
    body_slots: tuple[int, ...]
    has_top_empty_page: bool
    active_slots: tuple[int, ...]
    ready_slots: tuple[int, ...]
    terminal: bool
    raw: dict[str, object]


@dataclass(frozen=True, slots=True)
class _CurrentEpisodeAccess:
    work_id: str
    access_episode_id: str
    native: HanayumeNativeEpisodeAccess


@dataclass(frozen=True, slots=True)
class _TicketRequestStart:
    request: object
    kind: str
    requested_at: datetime
    exact_url: bool
    main_frame: bool
    non_navigation: bool
    no_redirect: bool
    used: bool = False


class _CurrentEpisodeAccessObserver:
    """Reduce only same-Page current-episode access and checkout responses."""

    MAX_RESPONSES = 24

    def __init__(self, episode_id: str, work_id: str) -> None:
        self._episode_id = episode_id
        self._work_id = work_id
        self._episode_path = f"/api/episodes/{episode_id}"
        self._page: Page | None = None
        self._starts: list[_TicketRequestStart] = []
        self._tasks: list[asyncio.Task[None]] = []
        self._access_tasks: list[tuple[datetime, asyncio.Task[None]]] = []
        self.access: list[_CurrentEpisodeAccess] = []
        self.invalid_access: list[tuple[datetime, str]] = []
        self.checkout_responses: list[tuple[datetime, int | None]] = []
        self.overflow = False
        self._request_listener = self._on_request
        self._response_listener = self._on_response

    def attach(self, page: Page) -> None:
        self._page = page
        page.on("request", self._request_listener)
        page.on("response", self._response_listener)

    def _on_request(self, request: Request) -> None:
        try:
            parsed = urlsplit(request.url)
            port = parsed.port
            path = parsed.path
            method = request.method.upper()
            if (
                parsed.scheme.lower() != "https"
                or (parsed.hostname or "").lower() != "hanayume.com"
                or parsed.username is not None
                or parsed.password is not None
                or port not in (None, 443)
            ):
                return
            if path == self._episode_path:
                kind, expected_method = "episode", "GET"
                exact_url = not parsed.query and not parsed.fragment
            elif path == "/api/checkout/rental":
                kind, expected_method = "checkout", "POST"
                exact_url = not parsed.query and not parsed.fragment
            else:
                return
            page = self._page
            frame_ok = page is not None and request.frame == page.main_frame
            non_navigation = not request.is_navigation_request()
            no_redirect = request.redirected_from is None
            exact_url = exact_url and method == expected_method and request.resource_type in {"fetch", "xhr"}
        except (AttributeError, PlaywrightError, ValueError):
            return
        if len(self._starts) >= self.MAX_RESPONSES:
            self.overflow = True
            return
        self._starts.append(
            _TicketRequestStart(
                request=request,
                kind=kind,
                requested_at=datetime.now(UTC),
                exact_url=exact_url,
                main_frame=frame_ok,
                non_navigation=non_navigation,
                no_redirect=no_redirect,
            )
        )

    def _on_response(self, response: Response) -> None:
        try:
            request = response.request
        except (AttributeError, PlaywrightError):
            return
        index = next(
            (
                i for i in range(len(self._starts) - 1, -1, -1)
                if self._starts[i].request is request and not self._starts[i].used
            ),
            None,
        )
        if index is None:
            duplicate = next(
                (
                    item for item in reversed(self._starts)
                    if item.request is request and item.used and item.kind == "episode"
                ),
                None,
            )
            if duplicate is not None:
                self.invalid_access.append(
                    (duplicate.requested_at, "duplicate_response_event")
                )
            return
        start = self._starts[index]
        self._starts[index] = _TicketRequestStart(
            request=start.request,
            kind=start.kind,
            requested_at=start.requested_at,
            exact_url=start.exact_url,
            main_frame=start.main_frame,
            non_navigation=start.non_navigation,
            no_redirect=start.no_redirect,
            used=True,
        )
        task = asyncio.create_task(self._capture(response, start=start))
        self._tasks.append(task)
        if start.kind == "episode":
            self._access_tasks.append((start.requested_at, task))

    async def _capture(self, response: Response, *, start: _TicketRequestStart) -> None:
        try:
            page = self._page
            if page is None or response.frame != page.main_frame:
                valid_frame = False
            else:
                valid_frame = True
            response_url = response.url
            parsed = urlsplit(response_url)
            exact_response_url = (
                parsed.scheme.lower() == "https"
                and (parsed.hostname or "").lower() == "hanayume.com"
                and parsed.username is None
                and parsed.password is None
                and parsed.port in (None, 443)
                and parsed.path == (
                    self._episode_path if start.kind == "episode" else "/api/checkout/rental"
                )
                and not parsed.query
                and not parsed.fragment
            )
            status = response.status
            if start.kind == "checkout":
                accepted = (
                    status == 200
                    and start.exact_url
                    and start.main_frame
                    and valid_frame
                    and start.non_navigation
                    and start.no_redirect
                    and exact_response_url
                )
                self.checkout_responses.append(
                    (start.requested_at, 200 if accepted else None)
                )
                return
            if not (
                status == 200
                and start.exact_url
                and start.main_frame
                and valid_frame
                and start.non_navigation
                and start.no_redirect
                and exact_response_url
            ):
                self.invalid_access.append((start.requested_at, "transport_or_identity"))
                return
            payload = await asyncio.wait_for(
                response.json(), timeout=TICKET_API_BODY_TIMEOUT_SECONDS
            )
            episode = payload.get("episode") if isinstance(payload, dict) else None
            series = episode.get("series") if isinstance(episode, dict) else None
            access = episode.get("access") if isinstance(episode, dict) else None
            episode_id = episode.get("id") if isinstance(episode, dict) else None
            work_id = series.get("id") if isinstance(series, dict) else None
            access_episode_id = access.get("episodeId") if isinstance(access, dict) else None
            access_type = access.get("accessType") if isinstance(access, dict) else None
            has_access = access.get("hasAccess") if isinstance(access, dict) else None
            remaining = access.get("timeRemainingInSeconds") if isinstance(access, dict) else None
            valid_ids = (
                episode_id == self._episode_id
                and access_episode_id == self._episode_id
                and work_id == self._work_id
                and isinstance(work_id, str)
                and WORK_ID_PATTERN.fullmatch(work_id) is not None
            )
            valid_state = (
                isinstance(access_type, str)
                and type(has_access) is bool
                and (
                    remaining is None
                    or type(remaining) is int
                    and 0 <= remaining <= MAX_EPISODE_ACCESS_SECONDS
                )
            )
            if not valid_ids or not valid_state:
                self.invalid_access.append((start.requested_at, "payload_identity_or_type"))
                return
            self.access.append(
                _CurrentEpisodeAccess(
                    work_id=work_id,
                    access_episode_id=access_episode_id,
                    native=HanayumeNativeEpisodeAccess(
                        episode_id=self._episode_id,
                        access_type=access_type,
                        has_access=has_access,
                        remaining_seconds=remaining,
                        requested_at=start.requested_at,
                    ),
                )
            )
        except (AttributeError, PlaywrightError, TimeoutError, TypeError, ValueError):
            if start.kind == "episode":
                self.invalid_access.append((start.requested_at, "response_body_unavailable"))

    def latest_access(self, *, after: datetime | None = None) -> _CurrentEpisodeAccess | None:
        if self.overflow:
            raise UnknownPageStateError("Hanayume current episode access observation overflowed")
        snapshots = [
            item for item in self.access
            if after is None or item.native.requested_at > after
        ]
        invalid = [
            at for at, _reason in self.invalid_access
            if after is None or at > after
        ]
        latest_at = max((item.native.requested_at for item in snapshots), default=None)
        if latest_at is not None and any(at >= latest_at for at in invalid):
            raise UnknownPageStateError("Hanayume current episode access response is ambiguous")
        if invalid and not snapshots:
            raise UnknownPageStateError("Hanayume current episode access response is invalid")
        if latest_at is None:
            return None
        latest = [item for item in snapshots if item.native.requested_at == latest_at]
        if len(latest) != 1:
            raise UnknownPageStateError("Hanayume current episode access response is duplicated")
        return latest[0]

    def has_pending_access(self, *, after: datetime | None = None) -> bool:
        return any(
            not start.used
            and start.kind == "episode"
            and (after is None or start.requested_at > after)
            for start in self._starts
        ) or any(
            not task.done() and (after is None or requested_at > after)
            for requested_at, task in self._access_tasks
        )

    def checkout_confirmed(self, *, after: datetime) -> bool:
        observed = [item for item in self.checkout_responses if item[0] > after]
        return len(observed) == 1 and observed[0][1] == 200

    async def wait_for_pending(self, timeout_seconds: float) -> bool:
        deadline = time.monotonic() + max(0.0, timeout_seconds)
        while True:
            pending = [task for task in self._tasks if not task.done()]
            if not pending:
                return True
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return False
            await asyncio.wait(pending, timeout=remaining)

    async def close(self) -> None:
        page, self._page = self._page, None
        if page is not None:
            try:
                page.remove_listener("request", self._request_listener)
                page.remove_listener("response", self._response_listener)
            except PlaywrightError:
                pass
        pending = [task for task in self._tasks if not task.done()]
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)


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


def _validate_history_row_copies(public_rows: object, history_rows: object) -> None:
    """Check only overlapping history copies; the public root remains authoritative."""

    if not isinstance(public_rows, list) or not isinstance(history_rows, list):
        raise UnknownPageStateError("Hanayume public/history episode rows are malformed")
    public_labels: dict[str, tuple[str, ...]] = {}
    for rows, seen, branch in (
        (public_rows, set(), "public"),
        (history_rows, set(), "history"),
    ):
        for row in rows:
            if (
                not isinstance(row, dict)
                or row.get("linkCount") != 1
                or not isinstance(row.get("href"), str)
                or not isinstance(row.get("labels"), list)
                or not all(isinstance(label, str) for label in row["labels"])
            ):
                raise UnknownPageStateError(f"Hanayume {branch} episode row is malformed")
            identity = parse_hanayume_episode_url(row["href"])
            if identity is None or identity.episode_id in seen:
                raise UnknownPageStateError(
                    f"Hanayume {branch} range has a foreign or duplicate episode ID"
                )
            seen.add(identity.episode_id)
            labels = tuple(row["labels"])
            if branch == "public":
                public_labels[identity.episode_id] = labels
            elif (
                identity.episode_id in public_labels
                and public_labels[identity.episode_id] != labels
            ):
                raise UnknownPageStateError(
                    "Hanayume public and history episode copies disagree on access labels"
                )


def _episode_row_signature(
    rows: object, *, allow_empty: bool = False
) -> tuple[tuple[str, tuple[str, ...]], ...]:
    """Validate a bounded observed episode list and retain its ordered raw signature."""

    if not isinstance(rows, list) or len(rows) > RANGE_PAGE_SIZE or (not rows and not allow_empty):
        raise UnknownPageStateError("Hanayume episode preview is empty or exceeds its row guard")
    signature: list[tuple[str, tuple[str, ...]]] = []
    seen_ids: set[str] = set()
    for row in rows:
        if (
            not isinstance(row, dict)
            or row.get("linkCount") != 1
            or not isinstance(row.get("href"), str)
            or not isinstance(row.get("labels"), list)
            or not all(isinstance(label, str) for label in row["labels"])
        ):
            raise UnknownPageStateError("Hanayume episode preview row is malformed")
        identity = parse_hanayume_episode_url(row["href"])
        if identity is None or identity.episode_id in seen_ids:
            raise UnknownPageStateError("Hanayume episode preview has a foreign or duplicate ID")
        seen_ids.add(identity.episode_id)
        signature.append((identity.episode_id, tuple(row["labels"])))
    return tuple(signature)


def _episode_dom_row_signature(
    rows: object, *, allow_empty: bool = False
) -> tuple[tuple[str, tuple[str, ...]], ...]:
    if not isinstance(rows, list):
        raise UnknownPageStateError("Hanayume episode preview rows are malformed")
    normalized: list[dict[str, object]] = []
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("hrefs"), list):
            raise UnknownPageStateError("Hanayume episode preview row is malformed")
        hrefs = row["hrefs"]
        normalized.append(
            {
                "linkCount": len(hrefs),
                "href": hrefs[0] if len(hrefs) == 1 else None,
                "labels": row.get("labels"),
            }
        )
    return _episode_row_signature(normalized, allow_empty=allow_empty)


def _signature_rows(
    signature: tuple[tuple[str, tuple[str, ...]], ...]
) -> list[dict[str, object]]:
    return [
        {
            "linkCount": 1,
            "href": f"{BASE_URL}/episodes/{episode_id}",
            "labels": list(labels),
        }
        for episode_id, labels in signature
    ]


def _preview_is_unselected(entries: object) -> bool:
    """Only the observed bare listing with no selected numeric range is a preview."""

    return (
        isinstance(entries, list)
        and bool(entries)
        and all(isinstance(entry, dict) and entry.get("current") is False for entry in entries)
    )


def _matches_episode_preview(
    observed: tuple[tuple[str, tuple[str, ...]], ...],
    preview: tuple[tuple[str, tuple[str, ...]], ...] | None,
) -> bool:
    return bool(preview) and (observed == preview or observed == tuple(reversed(preview)))


def _capture_output_format(captures: list[CaptureResult]) -> str:
    formats = {capture.mime_type for capture in captures}
    if formats == {"image/webp"}:
        return "webp"
    if formats == {"image/png"}:
        return "png"
    return "mixed"



def _expected_active_slots(current: int, body_slots: tuple[int, ...]) -> tuple[int, ...]:
    if current == 1:
        raw = (1,)
    else:
        raw = (current - 1, current)
    available = set(body_slots)
    return tuple(index for index in raw if index in available)


def _next_body_slots(
    captured_slots: list[int], body_slots: tuple[int, ...], count: int
) -> tuple[int, ...]:
    if tuple(captured_slots) != body_slots[: len(captured_slots)]:
        raise UnknownPageStateError("Hanayume captured body slot sequence changed")
    return body_slots[len(captured_slots) : len(captured_slots) + count]


def _slot_role(
    index: int, last_slot: int, classes: object, *, has_top_empty_page: bool = False
) -> str:
    if not isinstance(classes, list) or not all(isinstance(value, str) for value in classes):
        raise UnknownPageStateError("Hanayume viewer slot classes are malformed")
    actual = set(classes)
    if "-cv-page" not in actual:
        raise UnknownPageStateError("Hanayume viewer slot is missing its page wrapper")
    tails = {
        0: {"-cv-page", "mode-empty", "mode-pr", "mode-top-pr"},
        last_slot - 4: {"-cv-page", "mode-ci"},
        last_slot - 3: {"-cv-page", "mode-empty", "mode-pr"},
        last_slot - 2: {"-cv-page", "mode-empty", "mode-pr"},
        last_slot - 1: {"-cv-page", "mode-good"},
        last_slot: {"-cv-page", "mode-last"},
    }
    if index in tails:
        if actual != tails[index]:
            raise UnknownPageStateError("Hanayume non-body viewer slot changed structure")
        return "nonbody"
    if index == 1 and has_top_empty_page:
        if actual != {"-cv-page", "mode-empty"}:
            raise UnknownPageStateError("Hanayume top-empty lead-in slot changed structure")
        return "nonbody"
    if not 1 <= index <= last_slot - 5:
        raise UnknownPageStateError("Hanayume viewer slot is outside the known layout")
    state_classes = actual - {"-cv-page"}
    if not (
        state_classes.issubset({"mode-loaded", "mode-rendered"})
        or state_classes in (
            {"mode-loading"},
            {"mode-loading", "mode-req-render"},
            {"mode-loaded", "mode-req-render"},
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
    has_top_empty_page = "mode-has-top-emptypage" in raw["viewerClasses"]
    if not isinstance(slots, list) or not (
        len(slots) == total + 1
        or (not has_top_empty_page and total % 2 == 1 and len(slots) == total)
    ):
        raise UnknownPageStateError("Hanayume viewer page-wrapper count is incomplete")
    # The observed odd-body layout has an extra counter position, not a DOM page.
    # Keep seek/counter semantics separate from the fully validated physical tail.
    last_slot = len(slots) - 1
    body_start = 2 if has_top_empty_page else 1
    body_slots = tuple(range(body_start, last_slot - 4))
    if not body_slots:
        raise UnknownPageStateError("Hanayume viewer has no body slots in its observed layout")
    body_total = len(body_slots)
    active: list[int] = []
    ready: list[int] = []
    terminal = "mode-last-page" in raw["viewerClasses"]
    for index, slot in enumerate(slots):
        if not isinstance(slot, dict) or slot.get("index") != index:
            raise UnknownPageStateError("Hanayume viewer page-wrapper order is invalid")
        role = _slot_role(
            index, last_slot, slot.get("classes"), has_top_empty_page=has_top_empty_page
        )
        if has_top_empty_page and index == 1 and (
            slot.get("canvasCount") != 0 or slot.get("canvas") is not None
        ):
            raise UnknownPageStateError("Hanayume top-empty lead-in slot unexpectedly has a canvas")
        if role != "body":
            continue
        if index in body_slots and slot.get("wrapperCenterInViewport") is True:
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
        body_slots=body_slots,
        has_top_empty_page=has_top_empty_page,
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
    """Capture exact-free Hanayume body canvases with verified native pixels."""

    page_change_timeout_ms = 12_000

    def __init__(self) -> None:
        self._access_strategy: AccessStrategy = "auto"
        self._quota_resource: str | None = None
        self._access_consumption = AccessConsumption()
        self._ticket_observer: _SeriesAccessObserver | None = None
        self._current_ticket_observer: _CurrentEpisodeAccessObserver | None = None
        self._ticket_click_attempted = False
        self._ticket_entry_only = False
        self._ticket_click_started_at: datetime | None = None
        self._ticket_click_started_monotonic: float | None = None
        self._ticket_recovery_deadline: float | None = None
        self._ticket_fallback_reads = 0
        self._target_url: str | None = None
        self._episode_id: str | None = None
        self._expected_work_id: str | None = None
        self._opaque_work_key: str | None = None
        self._batch_route_guard_enabled = False
        self._batch_route_blocked_rsc = 0
        self._batch_route_blocked_unexpected = 0
        self._batch_route_abort_failures = 0
        self._batch_route_nonselected_responses = 0
        self._batch_route_fatal_reason: str | None = None
        self._work_id: str | None = None
        self._body_total: int | None = None
        self._body_slots: tuple[int, ...] | None = None
        self._has_top_empty_page: bool | None = None
        self._captured_slots: list[int] = []
        self._pending: tuple[str, int, tuple[int, ...]] | None = None
        self._ended = False
        self._last_capture_slots: tuple[int, ...] = ()
        self._capture_diagnostics: dict[str, object] = {}
        self._webp_encode_job: asyncio.Task[tuple[CaptureResult, ...]] | None = None
        self._capture_attempt: dict[str, object] | None = None
        self._initial_canvas_settle: dict[str, object] = {}

    async def prepare_page(self, page: Page) -> None:
        try:
            await page.add_init_script(OBSERVER_INIT_SCRIPT)
        except PlaywrightError as exc:
            self._capture_diagnostics = {"mode": "observer_unavailable", "reason": type(exc).__name__}

    def get_access_profile(self) -> AccessProfile:
        return hanayume_access_profile()

    def get_initialize_timeout_ms(self, default_ms: int) -> int:
        return max(default_ms, INITIALIZE_TIMEOUT_MS)

    async def configure_run(self, page: Page, access_strategy: AccessStrategy) -> None:
        if access_strategy not in {"auto", "direct", "quota"}:
            raise UnsupportedAccessStrategyError(
                f"Hanayume does not support access_strategy={access_strategy!r}"
            )
        await self._close_ticket_observer()
        await self._close_current_ticket_observer()
        self._access_strategy = access_strategy
        self._quota_resource = None
        self._access_consumption = AccessConsumption()
        self._ticket_click_attempted = False
        self._ticket_entry_only = False
        self._ticket_click_started_at = None
        self._ticket_click_started_monotonic = None
        self._ticket_recovery_deadline = None
        self._ticket_fallback_reads = 0
        self._reset_batch_route_guard()
        if self._expected_work_id is not None and self._episode_id is not None:
            await self._install_batch_route_guard(page)

    def _reset_batch_route_guard(self) -> None:
        self._batch_route_guard_enabled = False
        self._batch_route_blocked_rsc = 0
        self._batch_route_blocked_unexpected = 0
        self._batch_route_abort_failures = 0
        self._batch_route_nonselected_responses = 0
        self._batch_route_fatal_reason = None

    async def _install_batch_route_guard(self, page: Page) -> None:
        """Guard identity-bound Batch route requests before the initial navigation."""

        route = getattr(page, "route", None)
        if not callable(route) or self._episode_id is None:
            self._batch_route_fatal_reason = "route_guard_unavailable"
            raise UnknownPageStateError("Hanayume Batch route guard could not be installed")
        self._batch_route_guard_enabled = True
        try:
            page.on("response", self._observe_batch_route_response)
            for route_family in ("episodes", "series"):
                await route(
                    f"**://*/{route_family}/**",
                    self._handle_batch_navigation_route,
                )
        except Exception as exc:
            self._batch_route_fatal_reason = "route_guard_setup_failed"
            raise UnknownPageStateError(
                "Hanayume Batch route guard could not be installed"
            ) from exc

    def _batch_route_signature(self, request: object) -> bool:
        try:
            parsed = urlsplit(str(getattr(request, "url", "")))
            query = parse_qsl(parsed.query, keep_blank_values=True)
            headers = {
                str(key).casefold(): str(value)
                for key, value in (getattr(request, "headers", {}) or {}).items()
            }
            return (
                str(getattr(request, "method", "")).upper() == "GET"
                and self._is_allowed_batch_route_url(parsed)
                and self._is_observed_batch_route_path(parsed.path)
                and len(query) == 1
                and query[0][0] == "_rsc"
                and bool(query[0][1])
                and headers.get("rsc") == "1"
                and headers.get("next-router-prefetch") in {None, "1"}
                and str(getattr(request, "resource_type", "")) in {"fetch", "other"}
            )
        except Exception:  # noqa: BLE001 - malformed request metadata is never trusted
            return False

    @staticmethod
    def _is_allowed_batch_route_url(parsed) -> bool:
        try:
            return (
                parsed.scheme == "https"
                and parsed.hostname in ALLOWED_HOSTS
                and parsed.username is None
                and parsed.password is None
                and parsed.port in {None, 443}
            )
        except ValueError:
            return False

    @staticmethod
    def _is_observed_batch_route_path(path: str) -> bool:
        parts = path.split("/")
        if len(parts) not in {3, 4} or parts[0] != "" or parts[1] not in {
            "episodes",
            "series",
        }:
            return False
        if re.fullmatch(r"[0-9a-f]{13}", parts[2]) is None:
            return False
        if len(parts) == 3:
            return True
        suffix = parts[3]
        if parts[1] == "episodes":
            return suffix == "old" or re.fullmatch(r"[1-9][0-9]*", suffix) is not None
        return re.fullmatch(r"[1-9][0-9]*", suffix) is not None

    def _observe_batch_route_response(self, response: object) -> None:
        """Audit any off-target route response that escaped the pre-navigation guard."""

        if not self._batch_route_guard_enabled or self._episode_id is None:
            return
        try:
            parsed = urlsplit(str(getattr(response, "url", "")))
            if (
                self._is_allowed_batch_route_url(parsed)
                and parsed.path.startswith(("/episodes/", "/series/"))
                and parsed.path != f"/episodes/{self._episode_id}"
            ):
                self._batch_route_nonselected_responses += 1
                self._batch_route_fatal_reason = "nonselected_route_response_observed"
        except Exception:  # noqa: BLE001 - diagnostics must not interrupt Playwright
            self._batch_route_fatal_reason = "route_response_observation_failed"

    async def _handle_batch_navigation_route(self, route: object) -> None:
        """Pass the selected document/RSC and abort every off-target page route."""

        try:
            request = getattr(route, "request", None)
            parsed = urlsplit(str(getattr(request, "url", "")))
            path = parsed.path
            if parsed.hostname not in ALLOWED_HOSTS:
                await route.fallback()
                return
            target_path = f"/episodes/{self._episode_id}"
            headers = {
                str(key).casefold(): str(value)
                for key, value in (getattr(request, "headers", {}) or {}).items()
            }
            query = parse_qsl(parsed.query, keep_blank_values=True)
            method = str(getattr(request, "method", "")).upper()
            resource_type = str(getattr(request, "resource_type", ""))
            canonical_document = (
                path == target_path
                and self._is_allowed_batch_route_url(parsed)
                and method == "GET"
                and resource_type == "document"
                and not query
                and "rsc" not in headers
                and "next-router-prefetch" not in headers
            )
            selected_rsc = path == target_path and self._batch_route_signature(request)
            if canonical_document or selected_rsc:
                await route.fallback()
                return

            known_nonselected_rsc = (
                path != target_path
                and self._is_observed_batch_route_path(path)
                and self._batch_route_signature(request)
            )
            if known_nonselected_rsc:
                self._batch_route_blocked_rsc += 1
            else:
                self._batch_route_blocked_unexpected += 1
                if self._batch_route_fatal_reason is None:
                    self._batch_route_fatal_reason = "unrecognized_page_route_request"
            try:
                await route.abort(error_code="blockedbyclient")
            except Exception:  # noqa: BLE001 - failed aborts are fatal and remain visible
                self._batch_route_abort_failures += 1
                self._batch_route_fatal_reason = "page_route_abort_failed"
        except Exception:  # noqa: BLE001 - no routing callback exception may escape
            self._batch_route_blocked_unexpected += 1
            self._batch_route_fatal_reason = "page_route_handler_failed"
            try:
                await route.abort(error_code="blockedbyclient")
            except Exception:  # noqa: BLE001 - no safe fallback for an unknown route
                self._batch_route_abort_failures += 1
                self._batch_route_fatal_reason = "page_route_abort_failed"

    def _raise_if_batch_route_guard_failed(self) -> None:
        if self._batch_route_fatal_reason is not None:
            raise UnknownPageStateError(
                "Hanayume Batch blocked an unrecognized episode/work navigation request"
            )

    async def configure_quota_resource(self, page: Page, quota_resource: str | None) -> None:
        if quota_resource not in {None, "work_ticket"}:
            raise UnsupportedAccessStrategyError(
                f"Hanayume does not support quota_resource={quota_resource!r}"
            )
        if self._access_strategy == "quota" and quota_resource != "work_ticket":
            raise UnsupportedAccessStrategyError(
                "Hanayume quota access requires quota_resource='work_ticket'"
            )
        if self._access_strategy != "quota" and quota_resource is not None:
            raise UnsupportedAccessStrategyError(
                "Hanayume work_ticket requires access_strategy='quota'"
            )
        self._quota_resource = quota_resource
        if self._access_strategy == "quota":
            if self._episode_id is None or self._expected_work_id is None:
                raise UnsupportedAccessStrategyError(
                    "Hanayume Work Ticket observation requires configured work and episode identities"
                )
            observer = _SeriesAccessObserver()
            observer.attach(page)
            self._ticket_observer = observer
            current_observer = _CurrentEpisodeAccessObserver(
                self._episode_id, self._expected_work_id
            )
            current_observer.attach(page)
            self._current_ticket_observer = current_observer

    def get_access_consumption(self) -> AccessConsumption:
        return self._access_consumption

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
        self._raise_if_batch_route_guard_failed()
        if self._target_url is None or self._episode_id is None or page.url != self._target_url:
            raise UnknownPageStateError("Hanayume initial episode URL does not match its target")
        self._body_total = None
        self._body_slots = None
        self._has_top_empty_page = None
        self._captured_slots = []
        self._pending = None
        self._ended = False
        self._last_capture_slots = ()
        self._initial_canvas_settle = {}
        initial_work = await self._read_episode_work(page)
        if self._expected_work_id is not None and initial_work != self._expected_work_id:
            raise UnknownPageStateError("Hanayume episode belongs to a different Catalog work")
        if self._access_strategy == "quota":
            if self._expected_work_id is None or self._quota_resource != "work_ticket":
                raise UnknownPageStateError(
                    "Hanayume Work Ticket requires an identity-bound Catalog candidate"
                )
            await self._initialize_work_ticket_entry(page, entry_only=False)
        elif self._expected_work_id is None:
            await self._fresh_free_preflight(page, initial_work)
        elif self._access_strategy == "direct":
            await self._reject_central_work_ticket_gate(page)
        if page.url != self._target_url:
            if self._access_strategy == "quota":
                raise AccessConsumptionUnconfirmedError(
                    "Hanayume Work Ticket entry changed the target route; automatic navigation is forbidden"
                )
            await self._navigate_exact(page, self._target_url)
        await self._wait_for_episode(page, expected_work=initial_work)
        await self._wait_for_locator(page, SEEK_SELECTOR, state="attached")
        await self._wait_for_viewer_counter_readiness(page)
        first = await self._observe(page)
        self._body_total = first.body_total
        self._body_slots = first.body_slots
        self._has_top_empty_page = first.has_top_empty_page
        if first.terminal or first.current != 1 or first.seek_value != first.seek_max:
            seek = page.locator(SEEK_SELECTOR)
            try:
                await asyncio.wait_for(seek.focus(timeout=1_500), timeout=2.0)
                await asyncio.wait_for(seek.press("End", timeout=1_500), timeout=2.0)
            except (PlaywrightError, TimeoutError) as exc:
                raise UnknownPageStateError("Hanayume viewer could not rewind with its observed seek control") from exc
        if first.has_top_empty_page:
            first = await self._wait_for_observation(
                page,
                self._is_top_empty_intro,
                reason="Hanayume top-empty first page did not settle at its observed lead-in",
            )
            next_value = first.seek_value - first.seek_step
            if next_value < first.seek_min or next_value > first.seek_max:
                raise UnknownPageStateError("Hanayume first body seek is outside its observed range")
            await self._set_public_seek_value(
                page, first, next_value, failure="Hanayume first body public seek failed"
            )
            expected_first_spread = _expected_active_slots(3, first.body_slots)
            if expected_first_spread != (2, 3):
                raise UnknownPageStateError("Hanayume top-empty body does not start at slots 2 and 3")
            first = await self._wait_for_observation(
                page,
                lambda row: not row.terminal
                and row.current == 3
                and row.seek_value == row.seek_max - 2
                and row.active_slots == expected_first_spread
                and row.ready_slots == expected_first_spread,
                reason="Hanayume top-empty first body spread did not become ready",
                initial_canvas_slots=expected_first_spread,
            )
        else:
            first = await self._wait_for_observation(
                page,
                lambda row: not row.terminal
                and row.current == 1
                and row.seek_value == row.seek_max
                and row.active_slots == (1,)
                and row.ready_slots == (1,),
                reason="Hanayume viewer did not settle at its first body page",
                initial_canvas_slots=(1,),
            )
        self._work_id = initial_work

    async def initialize_entry_only(self, page: Page) -> None:
        """Confirm one Work Ticket entry without starting capture or packaging."""

        self._raise_if_batch_route_guard_failed()
        if self._access_strategy != "quota" or self._quota_resource != "work_ticket":
            raise UnsupportedAccessStrategyError(
                "Hanayume entry-only execution requires quota/work_ticket"
            )
        if (
            self._target_url is None
            or self._episode_id is None
            or self._expected_work_id is None
            or page.url != self._target_url
        ):
            raise AccessResourceUnavailableError("hanayume_discovery_refresh_required")
        work_id = await self._read_episode_work(page)
        if work_id != self._expected_work_id:
            raise AccessResourceUnavailableError("hanayume_discovery_refresh_required")
        self._ticket_entry_only = True
        await self._initialize_work_ticket_entry(page, entry_only=True)
        await self._wait_for_episode(page, expected_work=work_id)
        await self._wait_for_locator(page, SEEK_SELECTOR, state="attached")
        await self._wait_for_viewer_counter_readiness(page)
        observation = await self._observe(page)
        if observation.terminal or observation.current < 1 or observation.total < 1:
            raise UnknownPageStateError("Hanayume ticket entry did not reach a valid viewer state")
        self._work_id = work_id

    async def _close_ticket_observer(self) -> None:
        observer, self._ticket_observer = self._ticket_observer, None
        if observer is not None:
            await observer.close()

    async def _close_current_ticket_observer(self) -> None:
        observer, self._current_ticket_observer = self._current_ticket_observer, None
        if observer is not None:
            await observer.close()

    async def _read_ticket_entry_dom(self, page: Page) -> dict[str, object]:
        if self._episode_id is None or self._target_url is None or page.url != self._target_url:
            raise AccessResourceUnavailableError("hanayume_discovery_refresh_required")
        try:
            value = await asyncio.wait_for(
                page.evaluate(TICKET_ENTRY_SNAPSHOT_SCRIPT, self._episode_id),
                timeout=OBSERVATION_TIMEOUT_SECONDS,
            )
        except (PlaywrightError, TimeoutError) as exc:
            raise UnknownPageStateError("Hanayume ticket entry DOM observation failed") from exc
        if page.url != self._target_url or not isinstance(value, dict):
            raise AccessResourceUnavailableError("hanayume_discovery_refresh_required")
        return value

    async def _reject_central_work_ticket_gate(self, page: Page) -> None:
        """Reject only the observed, target-local charge action on direct entry."""

        self._raise_if_batch_route_guard_failed()
        if page.url != self._target_url:
            raise UnknownPageStateError("Hanayume direct Batch left its exact episode route")
        try:
            state = await asyncio.wait_for(
                page.evaluate(
                    """() => {
                      const all = selector => [...document.querySelectorAll(selector)];
                      const visible = node => {
                        if (!node) return false;
                        const style = getComputedStyle(node), rect = node.getBoundingClientRect();
                        return style.display !== 'none' && style.visibility !== 'hidden' &&
                          Number(style.opacity || '1') > 0 && rect.width > 0 && rect.height > 0;
                      };
                      const mains = all('div.ep-main-content.mode-charge');
                      const actions = all('div.ep-main-content.mode-charge > div.ep-charge > ' +
                        'div.ep-charge-act');
                      const action = actions.length === 1 ? actions[0] : null;
                      const tickets = action ? [...action.querySelectorAll('button[data-e2e="wfRead"]')] : [];
                      const loginControls = action ? [...action.querySelectorAll('a[href]')].filter(node => {
                        const href = node.getAttribute('href') || '';
                        const text = (node.innerText || '').replace(/\\s+/g, ' ').trim();
                        return /login|signin|sign-in/i.test(href) ||
                          /ログイン|サインイン|login/i.test(text);
                      }) : [];
                      return {
                        exactGate: mains.length === 1 && actions.length === 1 &&
                          actions[0].parentElement?.classList.contains('ep-charge') === true &&
                          actions[0].parentElement.parentElement === mains[0],
                        visibleTicketCount: tickets.filter(visible).length,
                        visibleLoginCount: loginControls.filter(visible).length
                      };
                    }"""
                ),
                timeout=OBSERVATION_TIMEOUT_SECONDS,
            )
        except (PlaywrightError, TimeoutError) as exc:
            raise UnknownPageStateError("Hanayume direct entry gate observation failed") from exc
        if not isinstance(state, dict):
            raise UnknownPageStateError("Hanayume direct entry gate observation is malformed")
        visible_gate = state.get("visibleTicketCount", 0) > 0 or state.get("visibleLoginCount", 0) > 0
        if visible_gate and state.get("exactGate") is not True:
            raise UnknownPageStateError("Hanayume direct entry gate ancestry is ambiguous")
        if state.get("exactGate") is True and visible_gate:
            raise AccessResourceUnavailableError(
                "hanayume_direct_entry_requires_work_ticket_or_login"
            )

    async def _wait_for_ticket_account(self, page: Page) -> dict[str, object]:
        deadline = time.monotonic() + TICKET_AUTH_READY_TIMEOUT_SECONDS
        while time.monotonic() < deadline:
            state = await self._read_ticket_entry_dom(page)
            root_state = state.get("rootState")
            if root_state == "no_user":
                raise AccessResourceUnavailableError("work_ticket_authentication_required")
            if root_state == "ready":
                self._validate_ticket_page_identity(state)
                if state.get("loginVisible") is True or state.get("overlayVisible") is True:
                    raise UnknownPageStateError(
                        "Hanayume ticket entry has a login link or visible overlay"
                    )
                return state
            if root_state not in {"missing", "loading"}:
                raise UnknownPageStateError(
                    "Hanayume target-local account state is unknown"
                )
            await asyncio.sleep(TICKET_POLL_INTERVAL_SECONDS)
        raise PageChangeTimeoutError(
            "Hanayume target-local account list did not reach its observed ready state"
        )

    def _validate_ticket_page_identity(self, state: dict[str, object]) -> None:
        if (
            self._episode_id is None
            or self._expected_work_id is None
            or state.get("routeExact") is not True
            or state.get("headerExact") is not True
            or state.get("episodePageExact") is not True
            or state.get("rootClasses") != ["mode-has-eps", "mode-user", "series-eplist"]
            or state.get("loginVisible") is not False
            or state.get("overlayVisible") is not False
        ):
            raise UnknownPageStateError("Hanayume target-local identity or account state is ambiguous")
        work_href = state.get("workHref")
        if (
            not isinstance(work_href, str)
            or parse_hanayume_work_url(work_href) != self._expected_work_id
        ):
            raise AccessResourceUnavailableError("hanayume_discovery_refresh_required")
        if (
            state.get("previewRootsExact") is not True
            or state.get("publicRowsValid") is not True
            or state.get("accountRowsValid") is not True
            or not isinstance(state.get("publicRowCount"), int)
            or state.get("publicRowCount", 0) < 1
            or not isinstance(state.get("accountRowCount"), int)
            or state.get("accountRowCount", 0) < 1
        ):
            raise UnknownPageStateError("Hanayume public or account preview is malformed")
        public_target_rows = state.get("publicTargetRows")
        target_rows = state.get("targetRows")
        public_target_links = state.get("publicTargetLinkCount")
        account_target_links = state.get("accountTargetLinkCount")
        if (
            not isinstance(public_target_rows, list)
            or not isinstance(target_rows, list)
            or not isinstance(public_target_links, int)
            or not isinstance(account_target_links, int)
            or public_target_links not in {0, 1}
            or account_target_links not in {0, 1}
            or len(public_target_rows) != public_target_links
            or len(target_rows) != account_target_links
            or (public_target_links == 1) != (account_target_links == 1)
            or state.get("accountOtherCurrentRowCount") != 0
        ):
            raise UnknownPageStateError("Hanayume public/account target preview is ambiguous")
        for row in [*public_target_rows, *target_rows]:
            if (
                not isinstance(row, dict)
                or row.get("titleCount") != 1
                or not isinstance(row.get("classes"), list)
                or not all(isinstance(name, str) for name in row["classes"])
                or not isinstance(row.get("rentalStats"), list)
                or not all(isinstance(text, str) for text in row["rentalStats"])
            ):
                raise UnknownPageStateError("Hanayume target preview row is incomplete")

    async def _wait_for_native_ticket_state(
        self,
        page: Page,
        *,
        requested_after: datetime | None = None,
        deadline: float,
    ) -> HanayumeNativeEpisodeAccess:
        if (
            self._ticket_observer is None
            or self._current_ticket_observer is None
            or self._expected_work_id is None
            or self._episode_id is None
        ):
            raise UnknownPageStateError("Hanayume native access observation is not configured")
        while time.monotonic() < deadline:
            if page.url != self._target_url:
                raise AccessResourceUnavailableError("hanayume_discovery_refresh_required")
            observer = self._ticket_observer
            current_observer = self._current_ticket_observer
            if observer.overflow or current_observer.overflow:
                raise UnknownPageStateError("Hanayume native access response observation overflowed")
            await observer.wait_for_pending(0.1)
            await current_observer.wait_for_pending(0.1)
            if current_observer.has_pending_access(after=requested_after):
                remaining = deadline - time.monotonic()
                if remaining > 0:
                    await asyncio.sleep(min(TICKET_POLL_INTERVAL_SECONDS, remaining))
                continue
            current = current_observer.latest_access(after=requested_after)
            rows = _latest_native_access_by_episode(
                tuple(observer.snapshots), work_id=self._expected_work_id
            )
            row = rows.get(self._episode_id)
            if row is not None and requested_after is not None and row.requested_at <= requested_after:
                row = None
            if current is not None:
                if current.work_id != self._expected_work_id or current.access_episode_id != self._episode_id:
                    raise UnknownPageStateError("Hanayume current episode access identity changed")
                if (
                    row is not None
                    and current.native.requested_at == row.requested_at
                    and current.native != row
                ):
                    raise UnknownPageStateError("Hanayume native access responses conflict")
                if row is None or current.native.requested_at >= row.requested_at:
                    return current.native
            if row is not None:
                return row
            await asyncio.sleep(TICKET_POLL_INTERVAL_SECONDS)
        raise PageChangeTimeoutError("Hanayume exact native access state did not arrive within its bound")

    @staticmethod
    def _ticket_account_row_state(state: dict[str, object]) -> str:
        rows = state.get("targetRows")
        if isinstance(rows, list) and not rows and state.get("publicTargetRows") == []:
            return "absent"
        if not isinstance(rows, list) or len(rows) != 1 or not isinstance(rows[0], dict):
            return "unknown"
        row = rows[0]
        classes = row.get("classes")
        rental_stats = row.get("rentalStats")
        if not isinstance(classes, list) or not isinstance(rental_stats, list):
            return "unknown"
        if classes in (
            ["mode-current", "mode-store-item-blank", "series-eplist-item"],
            ["mode-current", "mode-store-item-start", "series-eplist-item"],
        ):
            return "blank" if not rental_stats else "unknown"
        if (
            classes
            in (
                ["mode-current", "mode-read", "mode-store-item-start", "series-eplist-item"],
                ["mode-current", "mode-read", "mode-store-item-blank", "series-eplist-item"],
            )
            and len(rental_stats) == 1
            and isinstance(rental_stats[0], str)
            and "レンタル中" in rental_stats[0]
            and "閲覧期限" in rental_stats[0]
        ):
            return "read"
        return "unknown"

    def _latest_series_ticket_target(
        self, snapshots: tuple[object, ...], *, current_requested_at: datetime | None
    ) -> tuple[HanayumeNativeEpisodeAccess | None, datetime | None, datetime | None]:
        """Return the latest selected row, duplicate time, and foreign-work time."""

        if self._episode_id is None or self._expected_work_id is None:
            return None, None, None
        target_rows: list[HanayumeNativeEpisodeAccess] = []
        foreign_work_times: list[datetime] = []
        for snapshot in snapshots:
            work_id = getattr(snapshot, "work_id", None)
            rows = getattr(snapshot, "rows", ())
            for row in rows:
                if getattr(row, "episode_id", None) != self._episode_id:
                    continue
                requested_at = getattr(row, "requested_at", None)
                if not isinstance(requested_at, datetime):
                    continue
                if work_id != self._expected_work_id:
                    foreign_work_times.append(requested_at)
                else:
                    target_rows.append(row)
        latest_at = max((row.requested_at for row in target_rows), default=None)
        latest_rows = [row for row in target_rows if row.requested_at == latest_at]
        duplicate_at = latest_at if len(latest_rows) > 1 else None
        latest = latest_rows[0] if len(latest_rows) == 1 else None
        foreign_at = max(foreign_work_times, default=None)
        if (
            current_requested_at is not None
            and foreign_at is not None
            and foreign_at < current_requested_at
        ):
            foreign_at = None
        return latest, duplicate_at, foreign_at

    def _classify_ticket_prestate(
        self,
        native: HanayumeNativeEpisodeAccess,
        state: dict[str, object],
    ) -> str:
        self._validate_ticket_page_identity(state)
        if native.access_type != WAIT_AND_FREE_ACCESS_TYPE or native.has_access is None:
            return "unavailable"
        account_state = self._ticket_account_row_state(state)
        if account_state == "absent":
            # A series-level false row identifies a nominal candidate, but it
            # cannot prove the selected episode's current entitlement when both
            # episode previews omit the target. Require the exact current API
            # response that carries all three Catalog-bound identities.
            observer = self._current_ticket_observer
            current = observer.latest_access() if observer is not None else None
            if (
                current is None
                or current.work_id != self._expected_work_id
                or current.access_episode_id != self._episode_id
            ):
                return "unknown"
            current_state = (
                current.native.access_type,
                current.native.has_access,
                current.native.remaining_seconds,
            )
            selected_state = (
                native.access_type,
                native.has_access,
                native.remaining_seconds,
            )
            if current_state != selected_state:
                return "unknown"
            # A newer series snapshot may be the selected native row even when
            # the exact current-episode API observed the same entitlement a
            # little earlier. Request-start timing alone is not a conflict;
            # retain the exact endpoint as the authority for absent previews.
            native = current.native
        if native.has_access is True:
            if (
                native.remaining_seconds is not None
                and 0 < native.remaining_seconds <= MAX_EPISODE_ACCESS_SECONDS
                and account_state in {"read", "absent"}
            ):
                return "active"
            return "unknown"
        if native.remaining_seconds not in {None, 0}:
            return "unknown"
        if account_state in {"blank", "absent"}:
            return "ungranted"
        return "unknown"

    @staticmethod
    def _validate_work_ticket_control_snapshot(state: dict[str, object]) -> list[str]:
        classes = state.get("controlClasses")
        if (
            state.get("controlCount") != 1
            or state.get("controlText") != TICKET_CONTROL_LABEL
            or state.get("controlVisible") is not True
            or state.get("controlEnabled") is not True
            or state.get("controlCovered") is not False
            or state.get("chargeStructure") is not True
            or state.get("controlHasCost") is not False
            or state.get("controlHasInlineHandler") is not False
            or not isinstance(classes, list)
            or not all(isinstance(name, str) for name in classes)
        ):
            raise AccessResourceUnavailableError("work_ticket_unavailable")
        return classes

    async def _exact_work_ticket_control(self, page: Page) -> tuple[ElementHandle, list[str]]:
        state = await self._wait_for_ticket_account(page)
        self._validate_ticket_page_identity(state)
        if self._ticket_account_row_state(state) not in {"blank", "absent"}:
            raise UnknownPageStateError("Hanayume account row does not show the observed ungranted state")
        control_classes = self._validate_work_ticket_control_snapshot(state)
        control = page.locator(TICKET_CONTROL_SELECTOR)
        if await control.count() != 1:
            raise AccessResourceUnavailableError("work_ticket_unavailable")
        try:
            if not await control.is_visible() or not await control.is_enabled():
                raise AccessResourceUnavailableError("work_ticket_unavailable")
            handle = await control.element_handle()
            if handle is None:
                raise AccessResourceUnavailableError("work_ticket_unavailable")
            await control.click(trial=True, timeout=1_000)
        except PlaywrightError as exc:
            raise AccessResourceUnavailableError("work_ticket_unavailable") from exc
        return handle, control_classes

    async def _ticket_control_still_matches(
        self,
        control: ElementHandle,
        *,
        expected_classes: list[str],
    ) -> bool:
        try:
            return await control.evaluate(
                """(node, expected) => {
                  const selector = 'button[data-e2e="wfRead"]';
                  const visible = element => {
                    const style = getComputedStyle(element), rect = element.getBoundingClientRect();
                    return style.display !== 'none' && style.visibility !== 'hidden' &&
                      Number(style.opacity || '1') > 0 && rect.width > 0 && rect.height > 0;
                  };
                  const all = [...document.querySelectorAll(selector)];
                  const act = node.closest('.ep-charge-act');
                  const charge = act?.parentElement ?? null;
                  const main = charge?.parentElement ?? null;
                  const rect = node.getBoundingClientRect();
                  const center = document.elementFromPoint(rect.left + rect.width / 2,
                    rect.top + rect.height / 2);
                  return node.isConnected && all.length === 1 && all[0] === node &&
                    node.matches('div.ep-main-content.mode-charge > div.ep-charge > ' +
                      'div.ep-charge-act > button[data-e2e="wfRead"]') &&
                    (node.innerText || '').replace(/\\s+/g, ' ').trim() === '待つと無料で読む' &&
                    visible(node) && !node.disabled && node.getAttribute('aria-disabled') !== 'true' &&
                    !(center && center !== node && !node.contains(center)) &&
                    !!act && act.parentElement === charge && charge.classList.contains('ep-charge') &&
                    !!main && main.classList.contains('ep-main-content') &&
                    main.classList.contains('mode-charge') &&
                    !['data-price','data-cost','data-buy-price'].some(name => node.hasAttribute(name)) &&
                    !node.hasAttribute('onclick') &&
                    JSON.stringify([...node.classList].sort()) === JSON.stringify(expected);
                }""",
                expected_classes,
            )
        except (PlaywrightError, TypeError):
            return False

    async def _fetch_current_ticket_access(self, page: Page, *, deadline: float) -> bool:
        """Issue one bounded same-Page read-only refresh after a confirmed checkout."""

        if (
            self._current_ticket_observer is None
            or self._episode_id is None
            or self._target_url is None
            or page.url != self._target_url
        ):
            return False
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return False
        endpoint = f"{BASE_URL}/api/episodes/{self._episode_id}"
        try:
            result = await asyncio.wait_for(
                page.evaluate(
                    """async url => {
                      try {
                        const response = await fetch(url, {
                          method: 'GET', credentials: 'same-origin', cache: 'no-store',
                          redirect: 'error'
                        });
                        return {
                          status: response.status,
                          url: response.url,
                          redirected: response.redirected
                        };
                      } catch (_) {
                        return {status: null, url: null, redirected: null};
                      }
                    }""",
                    endpoint,
                ),
                timeout=min(TICKET_API_BODY_TIMEOUT_SECONDS, remaining),
            )
        except (PlaywrightError, TimeoutError):
            return False
        if page.url != self._target_url or not isinstance(result, dict):
            return False
        return (
            result.get("status") == 200
            and result.get("url") == endpoint
            and result.get("redirected") is False
        )

    async def _reconcile_work_ticket_consumption(
        self,
        page: Page,
        *,
        before: HanayumeNativeEpisodeAccess,
        click_started_at: datetime,
        deadline: float,
    ) -> bool:
        if self._ticket_recovery_deadline is None:
            self._ticket_recovery_deadline = deadline
        recovery_deadline = min(deadline, self._ticket_recovery_deadline)
        click_started_monotonic = self._ticket_click_started_monotonic
        if click_started_monotonic is None:
            click_started_monotonic = time.monotonic()
            self._ticket_click_started_monotonic = click_started_monotonic
        while time.monotonic() < recovery_deadline:
            try:
                if page.url != self._target_url:
                    raise AccessResourceUnavailableError("hanayume_discovery_refresh_required")
                series_observer = self._ticket_observer
                current_observer = self._current_ticket_observer
                if series_observer is None or current_observer is None:
                    raise UnknownPageStateError("Hanayume ticket observers are unavailable")
                series_drained = True
                current_drained = True
                for observer in (series_observer, current_observer):
                    remaining = recovery_deadline - time.monotonic()
                    if remaining <= 0:
                        break
                    drained = await observer.wait_for_pending(min(0.05, remaining))
                    if observer is series_observer:
                        series_drained = drained
                    else:
                        current_drained = drained
                if time.monotonic() >= recovery_deadline:
                    break
                if (
                    not series_drained
                    or not current_drained
                    or current_observer.has_pending_access(after=click_started_at)
                ):
                    await asyncio.sleep(
                        min(
                            TICKET_POLL_INTERVAL_SECONDS,
                            recovery_deadline - time.monotonic(),
                        )
                    )
                    continue
                current = current_observer.latest_access(after=click_started_at)
                series_native, series_duplicate_at, foreign_series_at = (
                    self._latest_series_ticket_target(
                        tuple(series_observer.snapshots),
                        current_requested_at=(
                            current.native.requested_at if current is not None else None
                        ),
                    )
                )
                if series_native is not None and series_native.requested_at <= click_started_at:
                    series_native = None
                series_ambiguous_after_current = (
                    series_duplicate_at is not None
                    and (
                        current is None
                        or series_duplicate_at >= current.native.requested_at
                    )
                )
                series_identity_conflict_after_current = foreign_series_at is not None
                if current is not None and (
                    current.work_id != self._expected_work_id
                    or current.access_episode_id != self._episode_id
                ):
                    raise UnknownPageStateError("Hanayume current episode access identity changed")
                if (
                    current is not None
                    and series_native is not None
                    and current.native.requested_at == series_native.requested_at
                    and current.native != series_native
                ):
                    raise UnknownPageStateError("Hanayume native access responses conflict")
                # Reconcile both natural authorities in request-start order. A newer
                # denial must not be hidden by an older positive response.
                latest_native: HanayumeNativeEpisodeAccess | None
                latest_source: str | None
                if current is None:
                    latest_native, latest_source = series_native, "series" if series_native else None
                elif series_native is None or current.native.requested_at >= series_native.requested_at:
                    latest_native, latest_source = current.native, "current"
                else:
                    latest_native, latest_source = series_native, "series"
                checkout_confirmed = current_observer.checkout_confirmed(after=click_started_at)
                current_native = current.native if current is not None else None
                current_positive_state = (
                    current_native is not None
                    and current_native.access_type == WAIT_AND_FREE_ACCESS_TYPE
                    and current_native.has_access is True
                    and current_native.remaining_seconds is not None
                    and 0 < current_native.remaining_seconds <= MAX_EPISODE_ACCESS_SECONDS
                )
                series_positive_state = (
                    series_native is not None
                    and series_native.access_type == WAIT_AND_FREE_ACCESS_TYPE
                    and series_native.has_access is True
                    and series_native.remaining_seconds is not None
                    and 0 < series_native.remaining_seconds <= MAX_EPISODE_ACCESS_SECONDS
                )
                newer_series_agrees = (
                    current_native is not None
                    and series_native is not None
                    and series_native.requested_at > current_native.requested_at
                    and current_positive_state
                    and series_positive_state
                )
                positive_current = (
                    before.has_access is False
                    and current_positive_state
                    and not series_ambiguous_after_current
                    and not series_identity_conflict_after_current
                    and (
                        (latest_source == "current" and latest_native is current_native)
                        or newer_series_agrees
                    )
                )
                if checkout_confirmed and positive_current:
                    assert current_native is not None
                    expiry_candidates = [
                        current_native.requested_at
                        + timedelta(seconds=current_native.remaining_seconds - 1)
                    ]
                    if newer_series_agrees:
                        assert series_native is not None and series_native.remaining_seconds is not None
                        expiry_candidates.append(
                            series_native.requested_at
                            + timedelta(seconds=series_native.remaining_seconds - 1)
                        )
                    self._access_consumption = AccessConsumption(
                        consumed=True,
                        resource="work_ticket",
                        consumed_at=datetime.now(UTC),
                        access_granted_until=min(expiry_candidates),
                    )
                    return True

                remaining = recovery_deadline - time.monotonic()
                if remaining <= 0:
                    break
                state = await asyncio.wait_for(
                    self._read_ticket_entry_dom(page), timeout=remaining
                )
                self._validate_ticket_page_identity(state)
                account_state = self._ticket_account_row_state(state)
                positive_series = (
                    before.has_access is False
                    and not series_ambiguous_after_current
                    and not series_identity_conflict_after_current
                    and latest_source == "series"
                    and latest_native is series_native
                    and series_native is not None
                    and series_native.access_type == WAIT_AND_FREE_ACCESS_TYPE
                    and series_native.has_access is True
                    and series_native.remaining_seconds is not None
                    and 0 < series_native.remaining_seconds <= MAX_EPISODE_ACCESS_SECONDS
                    and account_state == "read"
                )
                confirmed_native = current_native if positive_current else (
                    series_native if positive_series else None
                )
                if checkout_confirmed and confirmed_native is not None:
                    expiry_candidates = [
                        confirmed_native.requested_at
                        + timedelta(seconds=confirmed_native.remaining_seconds - 1)
                    ]
                    if positive_current and newer_series_agrees:
                        assert series_native is not None and series_native.remaining_seconds is not None
                        expiry_candidates.append(
                            series_native.requested_at
                            + timedelta(seconds=series_native.remaining_seconds - 1)
                        )
                    self._access_consumption = AccessConsumption(
                        consumed=True,
                        resource="work_ticket",
                        consumed_at=datetime.now(UTC),
                        access_granted_until=min(expiry_candidates),
                    )
                    return True
                if (
                    checkout_confirmed
                    and self._ticket_fallback_reads < 2
                    and time.monotonic() - click_started_monotonic
                    >= 0.25 + 0.35 * self._ticket_fallback_reads
                    and (
                        latest_native is None
                        or latest_native.has_access is False
                    )
                    and not (
                        current_positive_state
                        and current_native is not None
                        and (
                            series_ambiguous_after_current
                            or series_identity_conflict_after_current
                            or (
                                series_native is not None
                                and series_native.requested_at > current_native.requested_at
                                and not series_positive_state
                            )
                        )
                    )
                ):
                    self._ticket_fallback_reads += 1
                    await self._fetch_current_ticket_access(
                        page, deadline=recovery_deadline
                    )
            except AccessResourceUnavailableError:
                # Once a click has been attempted, route/work drift is never a
                # safe skip. Keep only the bounded native-response observer alive.
                remaining = max(0.0, recovery_deadline - time.monotonic())
                for observer in (
                    self._ticket_observer,
                    self._current_ticket_observer,
                ):
                    if observer is not None and remaining > 0:
                        await observer.wait_for_pending(min(0.1, remaining))
            except (PageChangeTimeoutError, PlaywrightError, UnknownPageStateError, TimeoutError):
                pass
            remaining = recovery_deadline - time.monotonic()
            if remaining > 0:
                await asyncio.sleep(min(TICKET_POLL_INTERVAL_SECONDS, remaining))
        return self._access_consumption.consumed

    async def _initialize_work_ticket_entry(self, page: Page, *, entry_only: bool) -> None:
        """Use one scoped native-confirmed action on the already-open episode Page."""

        self._raise_if_batch_route_guard_failed()
        if (
            self._access_strategy != "quota"
            or self._quota_resource != "work_ticket"
            or self._expected_work_id is None
            or self._episode_id is None
            or self._ticket_observer is None
            or self._current_ticket_observer is None
        ):
            raise UnsupportedAccessStrategyError("Hanayume Work Ticket entry is not configured")
        if self._ticket_click_attempted:
            raise AccessConsumptionUnconfirmedError(
                "Hanayume Work Ticket click was already attempted; automatic retry is forbidden"
            )
        if page.url != self._target_url:
            raise AccessResourceUnavailableError("hanayume_discovery_refresh_required")
        native_before_click: HanayumeNativeEpisodeAccess | None = None
        try:
            deadline = time.monotonic() + TICKET_AUTH_READY_TIMEOUT_SECONDS
            state = await self._wait_for_ticket_account(page)
            if await self._read_episode_work(page) != self._expected_work_id:
                raise AccessResourceUnavailableError("hanayume_discovery_refresh_required")
            native = await self._wait_for_native_ticket_state(page, deadline=deadline)
            prestate = self._classify_ticket_prestate(native, state)
            if prestate == "active":
                if entry_only:
                    raise AccessResourceUnavailableError("work_ticket_already_granted")
                return
            if prestate == "unavailable":
                raise AccessResourceUnavailableError("work_ticket_unavailable")
            if prestate != "ungranted":
                raise UnknownPageStateError("Hanayume native and account ticket states disagree")

            control, control_classes = await self._exact_work_ticket_control(page)
            # Confirm the native eligibility after the actionability trial, then
            # make the final target/control check the last awaited step pre-click.
            state_before_click = await self._wait_for_ticket_account(page)
            self._validate_ticket_page_identity(state_before_click)
            native_before_click = await self._wait_for_native_ticket_state(page, deadline=deadline)
            state_before_click = await self._wait_for_ticket_account(page)
            self._validate_ticket_page_identity(state_before_click)
            if (
                self._classify_ticket_prestate(native_before_click, state_before_click) != "ungranted"
                or native_before_click.requested_at < native.requested_at
            ):
                raise UnknownPageStateError("Hanayume Work Ticket state changed before its action")
            final_control_classes = self._validate_work_ticket_control_snapshot(state_before_click)
            if final_control_classes != control_classes or not await self._ticket_control_still_matches(
                control, expected_classes=control_classes
            ):
                raise AccessResourceUnavailableError(
                    "work_ticket_control_changed_before_action"
                )
            self._raise_if_batch_route_guard_failed()
            self._ticket_click_attempted = True
            click_started_at = datetime.now(UTC)
            self._ticket_click_started_at = click_started_at
            self._ticket_click_started_monotonic = time.monotonic()
            click_error: BaseException | None = None
            try:
                await control.click(timeout=2_000, no_wait_after=True)
            except BaseException as exc:  # noqa: BLE001 - reconcile one click even on cancellation
                click_error = exc
            self._ticket_recovery_deadline = (
                time.monotonic() + TICKET_RECOVERY_WINDOW_SECONDS
            )
            confirmed = await self._reconcile_work_ticket_consumption(
                page,
                before=native_before_click,
                click_started_at=click_started_at,
                deadline=self._ticket_recovery_deadline,
            )
            if click_error is not None:
                if not isinstance(click_error, asyncio.CancelledError) and not confirmed:
                    raise AccessConsumptionUnconfirmedError(
                        "Hanayume Work Ticket action failed without confirmed consumption; automatic retry is forbidden"
                    ) from click_error
                raise click_error
            if page.url != self._target_url:
                raise AccessConsumptionUnconfirmedError(
                    "Hanayume Work Ticket click changed the episode route; automatic navigation is forbidden"
                )
            if not confirmed:
                raise AccessConsumptionUnconfirmedError(
                    "Hanayume Work Ticket consumption was not confirmed; automatic retry is forbidden"
                )
        except AccessResourceUnavailableError as exc:
            if not self._ticket_click_attempted:
                raise
            if self._ticket_click_started_at is not None and not self._access_consumption.consumed:
                try:
                    if native_before_click is None:
                        raise AccessConsumptionUnconfirmedError(
                            "Hanayume Work Ticket click was attempted before native eligibility was retained"
                        )
                    await self._reconcile_work_ticket_consumption(
                        page,
                        before=native_before_click,
                        click_started_at=self._ticket_click_started_at,
                        deadline=(
                            self._ticket_recovery_deadline
                            if self._ticket_recovery_deadline is not None
                            else time.monotonic()
                        ),
                    )
                except (AccessResourceUnavailableError, PageChangeTimeoutError, PlaywrightError):
                    pass
            raise AccessConsumptionUnconfirmedError(
                "Hanayume Work Ticket action was attempted but the target state became unavailable; automatic retry is forbidden"
            ) from exc
        finally:
            await self._close_ticket_observer()
            await self._close_current_ticket_observer()

    @staticmethod
    def _is_top_empty_intro(observation: ViewerObservation) -> bool:
        slots = observation.raw.get("slots")
        first_slot = slots[1] if isinstance(slots, list) and len(slots) > 1 else None
        viewer_classes = observation.raw.get("viewerClasses")
        return (
            observation.has_top_empty_page
            and observation.current == 1
            and observation.seek_value == observation.seek_max
            and not observation.terminal
            and observation.active_slots == ()
            and observation.ready_slots == ()
            and isinstance(viewer_classes, list)
            and "mode-first-page" in viewer_classes
            and isinstance(first_slot, dict)
            and first_slot.get("classes") == ["-cv-page", "mode-empty"]
            and first_slot.get("canvasCount") == 0
            and first_slot.get("canvas") is None
            and first_slot.get("wrapperCenterInViewport") is True
        )

    async def _set_public_seek_value(
        self,
        page: Page,
        observation: ViewerObservation,
        value: int,
        *,
        failure: str,
    ) -> None:
        if (
            not isinstance(value, int)
            or value < observation.seek_min
            or value > observation.seek_max
            or (observation.seek_max - value) % observation.seek_step != 0
        ):
            raise UnknownPageStateError("Hanayume public seek value is outside its observed range")
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
            raise PageChangeTimeoutError(failure) from exc

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
        try:
            listing_authenticated = await _read_series_authentication(page, work_id=work_id)
        except (ValueError, TypeError) as exc:
            raise UnknownPageStateError(
                "Hanayume work-listing authentication state is unknown"
            ) from exc

        target_labels = _find_target_labels(initial.get("rows"), self._episode_id)
        preview_signature: tuple[tuple[str, tuple[str, ...]], ...] | None = None
        preview_unselected = False
        if target_labels is None:
            target_history_labels = _find_target_labels(
                initial.get("historyRows"), self._episode_id
            )
            preview_unselected = _preview_is_unselected(initial.get("ranges"))
            initial_rows = initial.get("rows")
            if (
                preview_unselected
                and target_history_labels is None
                and isinstance(initial_rows, list)
                and 0 < len(initial_rows) <= RANGE_PAGE_SIZE
            ):
                preview_signature = _episode_row_signature(initial_rows)
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
        expected_labels = tuple(target_labels)
        access = classify_hanayume_access(
            expected_labels, listing_authenticated=listing_authenticated
        )
        if access.access_mode != "free":
            raise UnknownPageStateError(
                "Hanayume target is not one exact currently eligible free row"
            )

        await self._navigate_exact(page, self._target_url or "")
        await self._wait_for_episode(page, expected_work=work_id)
        await self._validate_episode_free_row(
            page,
            expected_labels=expected_labels,
            listing_authenticated=listing_authenticated,
            expected_work=work_id,
            preview_signature=preview_signature,
            preview_unselected=preview_unselected,
        )

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

    async def _wait_for_viewer_counter_readiness(self, page: Page) -> None:
        if self._target_url is None:
            raise UnknownPageStateError("Hanayume viewer target identity is missing")
        deadline = time.monotonic() + VIEWER_COUNTER_READY_TIMEOUT_MS / 1000
        while True:
            if page.url != self._target_url:
                raise UnknownPageStateError("Hanayume viewer moved away before its counter became ready")
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise UnknownPageStateError("Hanayume viewer page counter did not become ready")
            try:
                ready = await asyncio.wait_for(
                    page.evaluate(VIEWER_COUNTER_READINESS_SCRIPT),
                    timeout=min(OBSERVATION_TIMEOUT_SECONDS, remaining),
                )
            except (PlaywrightError, TimeoutError) as exc:
                raise UnknownPageStateError(
                    "Hanayume viewer page counter readiness exceeded its bound"
                ) from exc
            if not isinstance(ready, bool):
                raise UnknownPageStateError("Hanayume viewer counter readiness is malformed")
            if ready:
                return
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise UnknownPageStateError("Hanayume viewer page counter did not become ready")
            await asyncio.sleep(
                min(VIEWER_COUNTER_POLL_INTERVAL_MS / 1000, remaining)
            )

    async def _read_range_page(self, page: Page) -> dict[str, object]:
        try:
            value = await asyncio.wait_for(page.evaluate(RANGE_SNAPSHOT_SCRIPT), timeout=OBSERVATION_TIMEOUT_SECONDS)
        except (PlaywrightError, TimeoutError) as exc:
            raise UnknownPageStateError("Hanayume range observation exceeded its timeout") from exc
        if (
            not isinstance(value, dict)
            or value.get("path") != urlsplit(page.url).path
            or value.get("structureReady") is not True
        ):
            raise UnknownPageStateError("Hanayume range observation URL is inconsistent")
        _validate_history_row_copies(value.get("rows"), value.get("historyRows"))
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

    async def _read_episode_row_state(
        self, page: Page
    ) -> tuple[
        tuple[str, ...] | None,
        tuple[tuple[str, tuple[str, ...]], ...] | None,
        tuple[tuple[str, tuple[str, ...]], ...] | None,
    ]:
        if self._target_url is None or page.url != self._target_url:
            raise UnknownPageStateError("Hanayume current URL does not match the target episode")
        if self._episode_id is None:
            raise UnknownPageStateError("Hanayume target episode identity is missing")
        try:
            value = await asyncio.wait_for(
                page.evaluate(
                    r"""() => {
                      const wrappers = [...document.querySelectorAll('.series-eplist-wrap')];
                      const mains = wrappers.flatMap(wrap => [...wrap.children]
                        .filter(node => node.classList.contains('series-eplist-main')));
                      const episodeMarkers = [...document.querySelectorAll('[data-e2e="pageEpisode"]')];
                      const episodePages = episodeMarkers.filter(node => node.tagName === 'DIV' &&
                        node.classList.contains('ep-main') &&
                        node.classList.contains('series-safe-filter-target'));
                      const episodePage = episodePages.length === 1 ? episodePages[0] : null;
                      const episodeModes = episodePage ? [...episodePage.children].filter(node =>
                        node.tagName === 'DIV' && node.classList.contains('series') &&
                        node.classList.contains('mode-ep') && !node.hasAttribute('data-e2e')) : [];
                      const episodeMode = episodeModes.length === 1 ? episodeModes[0] : null;
                      const allRoots = [...document.querySelectorAll('.series-eplist')];
                      const roots = [...document.querySelectorAll(
                        '.series-eplist[data-e2e="epList"]')];
                      const userRoots = [...document.querySelectorAll(
                        '.series-eplist[data-e2e="epListUser"]')];
                      const knownMode = episodeMarkers.length === 1 && episodePages.length === 1 &&
                        wrappers.length === 1 && mains.length === 1 && episodeModes.length === 1 &&
                        episodeMode?.parentElement === episodePage &&
                        wrappers[0].parentElement === episodeMode &&
                        mains[0].parentElement === wrappers[0];
                      const publicRoot = roots.length === 1 && knownMode &&
                        roots[0].parentElement === mains[0];
                      const validUserRoots = userRoots.length <= 1 && knownMode &&
                        userRoots.every(root => root.parentElement === mains[0] &&
                          root.classList.contains('series-eplist') && root.classList.contains('mode-user'));
                      const knownRoots = publicRoot && validUserRoots &&
                        allRoots.length === roots.length + userRoots.length;
                      const readRows = root => [...root.querySelectorAll(
                        '.series-eplist-item[data-e2e="eli"]')].map(row => ({
                          hrefs: [...row.querySelectorAll('a.series-eplist-item-link')].map(link => link.href),
                          labels: [...row.querySelectorAll('.series-eplist-item-access-text')]
                            .map(node => (node.innerText || '').replace(/\s+/g, ' ').trim())
                        }));
                      const allRows = [...document.querySelectorAll(
                        '.series-eplist-item[data-e2e="eli"]')].map(row => {
                          const branch = row.closest('.series-eplist[data-e2e]');
                          return {
                            branch: branch === roots[0] ? 'public' :
                              (branch === userRoots[0] ? 'user' : 'unknown'),
                            hrefs: [...row.querySelectorAll('a.series-eplist-item-link')].map(link => link.href),
                            labels: [...row.querySelectorAll('.series-eplist-item-access-text')]
                              .map(node => (node.innerText || '').replace(/\s+/g, ' ').trim())
                          };
                        });
                      return {
                        rootCount: roots.length, knownMode, publicRoot,
                        userRootCount: userRoots.length, validUserRoots, knownRoots,
                        publicRows: publicRoot ? readRows(roots[0]) : [],
                        historyRows: userRoots.length === 1 ? readRows(userRoots[0]) : [], allRows
                      };
                    }"""
                ),
                timeout=OBSERVATION_TIMEOUT_SECONDS,
            )
        except (PlaywrightError, TimeoutError) as exc:
            raise UnknownPageStateError("Hanayume current episode access row could not be read") from exc
        if page.url != self._target_url:
            raise UnknownPageStateError("Hanayume episode route changed during its row recheck")
        if (
            not isinstance(value, dict)
            or value.get("rootCount") != 1
            or value.get("knownMode") is not True
            or value.get("publicRoot") is not True
            or value.get("validUserRoots") is not True
            or value.get("knownRoots") is not True
        ):
            raise UnknownPageStateError("Hanayume public episode list is missing or ambiguous")
        rows = value.get("allRows")
        public_rows = value.get("publicRows")
        if not isinstance(rows, list) or not isinstance(public_rows, list):
            raise UnknownPageStateError("Hanayume current episode access row is malformed")
        target_copies: list[tuple[str, ...]] = []
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
            if row.get("branch") not in {"public", "user"}:
                raise UnknownPageStateError(
                    "Hanayume target-like episode copy is outside the known list branches"
                )
            if len(hrefs) != 1:
                raise UnknownPageStateError(
                    "Hanayume current episode row is ambiguous"
                )
            identity = parse_hanayume_episode_url(hrefs[0])
            if identity is None or identity.episode_id != self._episode_id:
                raise UnknownPageStateError(
                    "Hanayume current episode row URL is not the exact first-party target"
                )
            target_copies.append(tuple(row["labels"]))
        public_targets: list[tuple[str, ...]] = []
        for row in public_rows:
            if (
                not isinstance(row, dict)
                or not isinstance(row.get("hrefs"), list)
                or not all(isinstance(href, str) for href in row["hrefs"])
                or not isinstance(row.get("labels"), list)
                or not all(isinstance(label, str) for label in row["labels"])
            ):
                raise UnknownPageStateError("Hanayume public episode row is malformed")
            hrefs = row["hrefs"]
            target_like = False
            for href in hrefs:
                try:
                    target_like = target_like or urlsplit(href).path == expected_path
                except ValueError as exc:
                    raise UnknownPageStateError("Hanayume public episode row URL is invalid") from exc
            if not target_like:
                continue
            if len(hrefs) != 1:
                raise UnknownPageStateError("Hanayume public episode target row is ambiguous")
            identity = parse_hanayume_episode_url(hrefs[0])
            if identity is None or identity.episode_id != self._episode_id:
                raise UnknownPageStateError("Hanayume public episode URL is not the exact target")
            public_targets.append(tuple(row["labels"]))
        if len(public_targets) > 1:
            raise UnknownPageStateError("Hanayume current episode public row is duplicated")
        if public_targets:
            if not target_copies:
                raise UnknownPageStateError("Hanayume current episode public row is missing")
            if any(labels != public_targets[0] for labels in target_copies):
                raise UnknownPageStateError("Hanayume target-like episode copies disagree on access")
            return public_targets[0], None, None
        if target_copies:
            raise UnknownPageStateError("Hanayume target episode appears only in the history listing")

        history_rows = value.get("historyRows")
        if (
            not isinstance(history_rows, list)
            or len(rows) != len(public_rows) + len(history_rows)
            or any(
                not isinstance(row, dict) or row.get("branch") not in {"public", "user"}
                for row in rows
            )
        ):
            raise UnknownPageStateError("Hanayume preview row is outside the known public/history roots")
        public_signature = _episode_dom_row_signature(public_rows)
        history_signature = _episode_dom_row_signature(history_rows, allow_empty=True)
        _validate_history_row_copies(
            _signature_rows(public_signature), _signature_rows(history_signature)
        )
        return None, public_signature, history_signature

    async def _read_episode_row_labels(self, page: Page) -> list[tuple[str, ...]]:
        labels, _, _ = await self._read_episode_row_state(page)
        if labels is None:
            raise UnknownPageStateError("Hanayume current episode public row is missing")
        return [labels]

    async def _validate_episode_free_row(
        self,
        page: Page,
        *,
        expected_labels: tuple[str, ...],
        listing_authenticated: bool,
        expected_work: str,
        preview_signature: tuple[tuple[str, tuple[str, ...]], ...] | None,
        preview_unselected: bool,
    ) -> None:
        await self._wait_for_locator(page, LISTING_SELECTOR, state="visible")
        if await self._read_episode_work(page) != expected_work:
            raise UnknownPageStateError("Hanayume episode work changed during its entry recheck")
        target_labels, public_signature, _ = await self._read_episode_row_state(page)
        if target_labels is not None:
            if target_labels != expected_labels:
                raise UnknownPageStateError(
                    "Hanayume episode badge changed after the fresh work-listing check; free access is not confirmed"
                )
        elif (
            public_signature is None
            or not preview_unselected
            or not _matches_episode_preview(public_signature, preview_signature)
        ):
            raise UnknownPageStateError(
                "Hanayume current episode is absent outside the exact fresh public preview"
            )
        access = classify_hanayume_access(
            expected_labels, listing_authenticated=listing_authenticated
        )
        if access.access_mode != "free":
            raise UnknownPageStateError("Hanayume current episode is not currently free")

    async def _wait_for_episode(self, page: Page, *, expected_work: str) -> None:
        if self._target_url is None or page.url != self._target_url:
            raise UnknownPageStateError("Hanayume episode navigation changed target identity")
        observed_work = await self._read_episode_work(page)
        if observed_work != expected_work or (
            self._expected_work_id is not None and observed_work != self._expected_work_id
        ):
            raise UnknownPageStateError("Hanayume current episode work identity changed")

    async def _observe(
        self, page: Page, *, include_png: bool = False,
        stability_slots: tuple[int, ...] = (),
    ) -> ViewerObservation:
        self._raise_if_batch_route_guard_failed()
        try:
            raw = await asyncio.wait_for(
                page.evaluate(
                    SNAPSHOT_SCRIPT,
                    {"includePng": include_png, "stabilitySlots": list(stability_slots)},
                ),
                timeout=OBSERVATION_TIMEOUT_SECONDS,
            )
        except (PlaywrightError, TimeoutError) as exc:
            raise UnknownPageStateError("Hanayume viewer observation exceeded its timeout") from exc
        self._raise_if_batch_route_guard_failed()
        if not isinstance(raw, dict) or raw.get("url") != page.url:
            raise UnknownPageStateError("Hanayume viewer observation changed URL")
        expected_url = self._target_url
        if expected_url is not None and page.url != expected_url:
            raise UnknownPageStateError("Hanayume viewer moved away from the selected episode")
        observation = _parse_viewer_observation(raw)
        if self._body_slots is not None and (
            observation.body_slots != self._body_slots
            or observation.body_total != self._body_total
            or observation.has_top_empty_page != self._has_top_empty_page
        ):
            raise UnknownPageStateError("Hanayume viewer body layout changed during the attempt")
        return observation

    async def _wait_for_observation(
        self, page: Page, predicate, *, reason: str,
        initial_canvas_slots: tuple[int, ...] = (),
    ) -> ViewerObservation:
        started = time.monotonic()
        timeout_ms = (
            INITIAL_CANVAS_SETTLE_TIMEOUT_MS if initial_canvas_slots
            else self.page_change_timeout_ms
        )
        deadline = started + timeout_ms / 1000
        previous: tuple[object, ...] | None = None
        stable = 0
        quiet_since = started
        last: ViewerObservation | None = None
        while time.monotonic() < deadline:
            if initial_canvas_slots:
                try:
                    observation = await asyncio.wait_for(
                        self._observe(page, stability_slots=initial_canvas_slots),
                        timeout=max(0, deadline - time.monotonic()),
                    )
                except TimeoutError:
                    break
            else:
                observation = await self._observe(page)
            last = observation
            signature = (
                observation.current,
                observation.total,
                observation.seek_value,
                observation.active_slots,
                observation.ready_slots,
                observation.terminal,
                observation.body_slots,
                observation.has_top_empty_page,
            )
            ready = predicate(observation)
            if initial_canvas_slots:
                # Startup can reset/redraw identical pixels after the ready classes appear.
                # Wait for a quiet first canvas; do not weaken the later native proof gate.
                signature += (
                    observation.raw.get("canvasStability"),
                    observation.raw.get("viewport"),
                    tuple(observation.raw["slots"][slot] for slot in initial_canvas_slots),
                )
                now = time.monotonic()
                if not ready or signature != previous:
                    quiet_since = now
                settled = ready and (now - quiet_since) * 1000 >= INITIAL_CANVAS_QUIET_MS
                self._initial_canvas_settle = {
                    "status": "settled" if settled else "waiting",
                    "quiet_ms": INITIAL_CANVAS_QUIET_MS,
                    "timeout_ms": timeout_ms,
                    "elapsed_ms": round((now - started) * 1000, 3),
                    "canvas_tracking": observation.raw.get("canvasStability") is not None,
                    "last_stability": observation.raw.get("canvasStability"),
                }
                if settled:
                    return observation
            elif ready and signature == previous:
                stable += 1
                if stable >= 2:
                    return observation
            else:
                stable = 0
            previous = signature
            remaining = deadline - time.monotonic()
            if remaining > 0:
                interval_ms = INITIAL_CANVAS_POLL_INTERVAL_MS if initial_canvas_slots else 150
                await page.wait_for_timeout(min(interval_ms, int(remaining * 1000)))
        if initial_canvas_slots:
            self._initial_canvas_settle["status"] = "timeout"
            self._initial_canvas_settle["elapsed_ms"] = round((time.monotonic() - started) * 1000, 3)
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
                and self._body_slots is not None
                and len(self._captured_slots) == self._body_total
                and tuple(self._captured_slots) == self._body_slots
                and observation.ready_slots == ()
            ):
                self._ended = True
                await self._clear_native_cache(page)
                return PageState.END
            raise UnknownPageStateError("Hanayume reached END before all body slots were captured")
        expected = _expected_active_slots(observation.current, observation.body_slots)
        if observation.active_slots != expected:
            return PageState.LOADING
        if observation.ready_slots != expected:
            return PageState.LOADING
        if not expected:
            raise UnknownPageStateError("Hanayume viewer is at a non-body lead-in state")
        expected_next = _next_body_slots(self._captured_slots, observation.body_slots, len(expected))
        if expected != expected_next:
            raise UnknownPageStateError("Hanayume body slot order has a gap or repetition")
        if self._access_strategy == "direct":
            await self._reject_central_work_ticket_gate(page)
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
        self._raise_if_batch_route_guard_failed()
        self._capture_attempt = None
        try:
            return await asyncio.wait_for(
                self._capture_page_within_budget(page), timeout=CAPTURE_BUDGET_SECONDS
            )
        except TimeoutError as exc:
            self._capture_diagnostics = {
                "mode": "capture_failed",
                "reason": "capture_budget_exceeded",
            }
            raise UnknownPageStateError("Hanayume atomic capture exceeded its adapter budget") from exc
        finally:
            await self._release_capture_attempt(page)

    async def _capture_page_within_budget(self, page: Page) -> tuple[CaptureResult, ...] | None:
        self._raise_if_batch_route_guard_failed()
        observation = await self._observe(page)
        expected = _expected_active_slots(observation.current, observation.body_slots)
        if not expected:
            raise UnknownPageStateError("Hanayume capture cannot include a non-body lead-in")
        next_slots = _next_body_slots(self._captured_slots, observation.body_slots, len(expected))
        if observation.terminal or not expected or expected != next_slots:
            raise UnknownPageStateError("Hanayume capture is not the next complete body page/spread")
        if observation.active_slots != expected or observation.ready_slots != expected:
            raise UnknownPageStateError("Hanayume current spread is missing a ready body canvas")
        if self._webp_encode_job is not None and not self._webp_encode_job.done():
            raise UnknownPageStateError("Hanayume previous bounded WebP encode is still running")
        episode_path = urlsplit(self._target_url or "").path
        self._capture_attempt = {
            "expectedSlots": list(expected),
            "expectedBodySlots": list(observation.body_slots),
            "hasTopEmptyPage": observation.has_top_empty_page,
            "episodePath": episode_path,
            "token": None,
        }
        try:
            self._raise_if_batch_route_guard_failed()
            raw = await asyncio.wait_for(
                page.evaluate(
                    COLLECT_CAPTURE_SCRIPT,
                    {
                        "expectedSlots": list(expected),
                        "expectedCurrent": observation.current,
                        "expectedBodyTotal": observation.body_total,
                        "expectedBodySlots": list(observation.body_slots),
                        "hasTopEmptyPage": observation.has_top_empty_page,
                        "episodePath": episode_path,
                    },
                ),
                timeout=OBSERVATION_TIMEOUT_SECONDS * 2,
            )
        except (PlaywrightError, TimeoutError) as exc:
            raise UnknownPageStateError("Hanayume atomic canvas capture exceeded its bound") from exc
        if not isinstance(raw, dict) or raw.get("ok") is not True:
            reason = raw.get("reason") if isinstance(raw, dict) else "malformed_capture_result"
            if reason not in {"capture_observer_missing", "observer_integrity_lost"}:
                self._capture_diagnostics = {"mode": "capture_failed", "reason": str(reason)}
                raise UnknownPageStateError("Hanayume selected canvas changed or could not be read")
            rendered = await self._observe(page, include_png=True)
            if (
                rendered.current != observation.current
                or rendered.body_total != observation.body_total
                or rendered.body_slots != observation.body_slots
                or rendered.has_top_empty_page != observation.has_top_empty_page
                or rendered.active_slots != expected
                or rendered.ready_slots != expected
            ):
                raise UnknownPageStateError("Hanayume clean rendered-canvas fallback changed state")
            slots = rendered.raw.get("slots")
            if not isinstance(slots, list):
                raise UnknownPageStateError("Hanayume rendered-canvas fallback slots are missing")
            captures: list[CaptureResult] = []
            for index in expected:
                slot = slots[index]
                canvas = slot.get("canvas") if isinstance(slot, dict) else None
                if not isinstance(canvas, dict) or canvas.get("ready") is not True or canvas.get("visible") is not True:
                    raise UnknownPageStateError("Hanayume rendered-canvas fallback is not ready")
                width, height = canvas.get("width"), canvas.get("height")
                if not isinstance(width, int) or not isinstance(height, int):
                    raise UnknownPageStateError("Hanayume rendered-canvas fallback dimensions are invalid")
                data = _decode_canvas_png(canvas.get("png"), width=width, height=height)
                captures.append(CaptureResult(data, width, height, "image/png", ".png"))
            self._capture_diagnostics = {
                "mode": "rendered_body_canvas_png",
                "reason": str(reason),
                "slots": list(expected),
                "output_dimensions": [[item.width, item.height] for item in captures],
                "output_formats": [item.mime_type for item in captures],
            }
            self._captured_slots.extend(expected)
            self._last_capture_slots = expected
            return tuple(captures)
        raw_token = raw.get("token")
        if isinstance(raw_token, str) and self._capture_attempt is not None:
            self._capture_attempt["token"] = raw_token
        current_observation = _parse_viewer_observation(raw.get("observation"))
        if (
            current_observation.current != observation.current
            or current_observation.body_total != observation.body_total
            or current_observation.body_slots != observation.body_slots
            or current_observation.has_top_empty_page != observation.has_top_empty_page
            or current_observation.active_slots != expected
            or current_observation.ready_slots != expected
        ):
            raise UnknownPageStateError("Hanayume selected spread changed during atomic readback")
        mode = raw.get("mode")
        if mode not in {"native", "rendered"}:
            raise UnknownPageStateError("Hanayume capture mode is unknown")
        images = decode_capture_images(
            raw.get("images"), expected_slots=expected, require_opaque=mode == "native"
        )
        if mode == "native":
            if any((image.width, image.height) != (960, 1540) for image in images):
                raise UnknownPageStateError("Hanayume native capture dimensions are not source-native")
            token = raw_token
            if not isinstance(token, str) or not token:
                raise UnknownPageStateError("Hanayume native capture proof token is missing")
            encode_started = time.monotonic()
            encode_task = asyncio.create_task(asyncio.to_thread(encode_native_webp, images))
            self._webp_encode_job = encode_task
            encode_task.add_done_callback(self._clear_webp_encode_job)
            try:
                captures = await asyncio.wait_for(asyncio.shield(encode_task), timeout=6.0)
            except TimeoutError as exc:
                self._capture_diagnostics = {
                    "mode": "capture_failed",
                    "reason": "native_encode_timeout",
                    "source_slots": list(expected),
                }
                raise UnknownPageStateError("Hanayume bounded native image encoding timed out") from exc
            except Exception:  # noqa: BLE001 - retain the same already-verified native PNGs
                captures = tuple(
                    CaptureResult(item.png, item.width, item.height, "image/png", ".png")
                    for item in images
                )
            encode_elapsed_ms = round((time.monotonic() - encode_started) * 1000, 3)
            verified = await self._verify_native_capture(page, token)
            if not verified:
                verification = self._capture_diagnostics.get("verification", {})
                self._capture_diagnostics = {
                    "mode": "capture_failed",
                    "reason": "native_target_changed_after_encoding",
                    "source_slots": list(expected),
                    "encode_elapsed_ms": encode_elapsed_ms,
                    "verification": verification,
                }
                detail = verification.get("reason", "unknown") if isinstance(verification, dict) else "unknown"
                raise UnknownPageStateError(
                    "Hanayume selected canvas changed after native image encoding "
                    f"(verification={detail})"
                )
            output_format = _capture_output_format(captures)
            self._capture_diagnostics = {
                "mode": f"source_canvas_lossless_{output_format}",
                "reason": raw.get("reason"),
                "slots": list(expected),
                "source_dimensions": [960, 1540],
                "output_dimensions": [[item.width, item.height] for item in captures],
                "output_formats": [item.mime_type for item in captures],
            }
        else:
            slots = observation.raw.get("slots")
            if not isinstance(slots, list):
                raise UnknownPageStateError("Hanayume canvas wrapper list disappeared during capture")
            for index, image in zip(expected, images, strict=True):
                slot = slots[index]
                canvas = slot.get("canvas") if isinstance(slot, dict) else None
                if (
                    not isinstance(canvas, dict)
                    or canvas.get("ready") is not True
                    or canvas.get("visible") is not True
                    or (canvas.get("width"), canvas.get("height")) != (image.width, image.height)
                ):
                    raise UnknownPageStateError("Hanayume rendered fallback dimensions changed")
            captures = tuple(
                CaptureResult(image.png, image.width, image.height, "image/png", ".png")
                for image in images
            )
            self._capture_diagnostics = {
                "mode": "rendered_body_canvas_png",
                "reason": raw.get("reason"),
                "slots": list(expected),
                "output_dimensions": [[item.width, item.height] for item in captures],
                "output_formats": [item.mime_type for item in captures],
            }
        self._captured_slots.extend(expected)
        self._last_capture_slots = expected
        return tuple(captures)

    def _clear_webp_encode_job(self, task: asyncio.Task[tuple[CaptureResult, ...]]) -> None:
        if self._webp_encode_job is task:
            self._webp_encode_job = None
        if not task.cancelled():
            try:
                task.exception()
            except asyncio.CancelledError:
                pass

    async def _verify_native_capture(self, page: Page, token: str) -> bool:
        try:
            value = await asyncio.wait_for(
                page.evaluate(VERIFY_CAPTURE_SCRIPT, token),
                timeout=OBSERVATION_TIMEOUT_SECONDS,
            )
        except TimeoutError:
            self._capture_diagnostics["verification"] = {
                "ok": False, "reason": "verification_timeout",
            }
            return False
        except PlaywrightError:
            self._capture_diagnostics["verification"] = {
                "ok": False, "reason": "verification_evaluation_failed",
            }
            return False
        if not isinstance(value, dict) or not isinstance(value.get("ok"), bool):
            value = {"ok": False, "reason": "verification_result_malformed"}
        self._capture_diagnostics["verification"] = value
        return value["ok"] is True

    async def _release_capture_attempt(self, page: Page) -> None:
        attempt = self._capture_attempt
        self._capture_attempt = None
        if attempt is None:
            return
        try:
            await asyncio.wait_for(
                page.evaluate(
                    RELEASE_CAPTURE_SCRIPT,
                    {
                        "token": attempt.get("token"),
                        "expectedSlots": attempt.get("expectedSlots"),
                        "expectedBodySlots": attempt.get("expectedBodySlots"),
                        "hasTopEmptyPage": attempt.get("hasTopEmptyPage"),
                        "episodePath": attempt.get("episodePath"),
                    },
                ),
                timeout=0.5,
            )
        except (PlaywrightError, TimeoutError):
            return

    async def get_content_identity(self, page: Page) -> ContentIdentity:
        observation = await self._observe(page)
        expected = _expected_active_slots(observation.current, observation.body_slots)
        if not expected:
            raise UnknownPageStateError("Hanayume non-body lead-in has no content identity")
        next_slots = _next_body_slots(self._captured_slots, observation.body_slots, len(expected))
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
        if self._body_slots is None or self._captured_slots != list(self._body_slots[: len(self._captured_slots)]):
            raise UnknownPageStateError("Hanayume captured body page sequence is not contiguous")
        if (
            observation.terminal
            or observation.ready_slots != self._last_capture_slots
            or observation.active_slots != _expected_active_slots(observation.current, observation.body_slots)
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
        await self._set_public_seek_value(
            page,
            observation,
            next_value,
            failure="Hanayume observed public seek input could not advance",
        )
        self._pending = (
            "spread",
            observation.current,
            _expected_active_slots(observation.current + 2, observation.body_slots),
        )

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
            if (
                self._body_slots is None
                or len(self._captured_slots) != observation.body_total
                or tuple(self._captured_slots) != self._body_slots
            ):
                raise UnknownPageStateError("Hanayume terminal UI arrived before complete body coverage")
            self._ended = True
            self._pending = None
            await self._clear_native_cache(page)
            return
        observation = await self._wait_for_observation(
            page,
            lambda row: not row.terminal
            and row.current == previous_current + 2
            and row.active_slots == expected_slots
            and row.ready_slots == expected_slots,
            reason="Hanayume next spread did not render in exact slot order",
        )
        expected_next = _next_body_slots(self._captured_slots, observation.body_slots, len(expected_slots))
        if observation.ready_slots != expected_next:
            raise UnknownPageStateError("Hanayume spread advance skipped or repeated body slots")
        self._pending = None

    async def collect_debug_metadata(self, page: Page) -> dict[str, object]:
        del page
        return {
            "capture_mode": self._capture_diagnostics.get("mode", "not_started"),
            "capture": dict(self._capture_diagnostics),
            "episode_id": self._episode_id,
            "captured_body_slots": len(self._captured_slots),
            "body_total": self._body_total,
            "last_slots": list(self._last_capture_slots),
            "source_native": str(self._capture_diagnostics.get("mode", "")).startswith("source_canvas_"),
            "initial_canvas_settle": dict(self._initial_canvas_settle),
            "batch_route_guard": {
                "enabled": self._batch_route_guard_enabled,
                "blocked_nonselected_rsc_attempts": self._batch_route_blocked_rsc,
                "blocked_unexpected_attempts": self._batch_route_blocked_unexpected,
                "abort_failures": self._batch_route_abort_failures,
                "nonselected_route_responses": self._batch_route_nonselected_responses,
                "fatal_reason": self._batch_route_fatal_reason,
            },
        }

    async def _clear_native_cache(self, page: Page) -> None:
        try:
            await asyncio.wait_for(
                page.evaluate("() => window.__hanayumeNativeCapture?.clear?.()"),
                timeout=1.0,
            )
        except (PlaywrightError, TimeoutError):
            return


__all__ = ["HanayumeAdapter"]
