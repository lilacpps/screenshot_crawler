"""Free-only rendered-page capture for the observed YanmagaWeb reader."""

from __future__ import annotations

import re
from dataclasses import dataclass
from hashlib import sha256
from itertools import pairwise
from math import isfinite
from time import monotonic
from urllib.parse import quote, urlsplit, urlunsplit

from playwright.async_api import Error as PlaywrightError
from playwright.async_api import Locator, Page

from screenshot_crawler.core.access_guard import AccessProfile
from screenshot_crawler.core.capture import CaptureResult, capture_locator
from screenshot_crawler.core.errors import (
    AccessResourceUnavailableError,
    PageChangeTimeoutError,
    UnknownPageStateError,
    UnsupportedAccessStrategyError,
)
from screenshot_crawler.core.models import AccessStrategy, ContentContext, ContentIdentity
from screenshot_crawler.core.state import PageState
from screenshot_crawler.site_adapters.base import SiteAdapter
from screenshot_crawler.site_adapters.yanmaga.access import yanmaga_access_profile
from screenshot_crawler.site_adapters.yanmaga.discovery import (
    SITE_HOST,
    YanmagaDiscoveryAdapter,
    YanmagaEpisodeParts,
    YanmagaListingRow,
    YanmagaWorkParts,
    parse_yanmaga_episode_url,
    parse_yanmaga_work_url,
)
from screenshot_crawler.watchlist.models import WatchlistTarget

VIEWPORT_WIDTH = 2560
VIEWPORT_HEIGHT = 1800
PAGE_CHANGE_TIMEOUT_MS = 15_000
INITIALIZE_TIMEOUT_MS = 90_000
RENDER_POLL_MS = 100
STABLE_READS_REQUIRED = 3
MAX_BODY_PAGES = 2_000
MAX_REWIND_TURNS = MAX_BODY_PAGES
SEGMENT_EDGE_TOLERANCE_PX = 3.0
FINAL_SEGMENT_BOTTOM_UNDERFLOW_PX = 4.0
FINAL_SEGMENT_BOTTOM_OVERFLOW_PX = 3.0

_COMPOSITE_ID = re.compile(r"^(?P<slug>.+):(?P<episode>[0-9a-f]{32})$")
_VIEWER_PATH = re.compile(
    r"^/viewer/comics/(?P<slug>[^/]+)/(?P<episode>[0-9a-f]{32})$"
)
_VIEWER_CID_QUERY = re.compile(r"^cid=[A-Za-z0-9]{20}$")
_PAGE_COUNTER = re.compile(r"^(?P<current>[1-9][0-9]*)/(?P<total>[1-9][0-9]*)$")
_PAGE_ID = re.compile(r"^content-p(?P<index>[1-9][0-9]*)$")
_BANNER_ID = re.compile(r"^banners-p(?:notice_banner|after_viewer)_[1-9][0-9]*$")
_ALLOWED_AUXILIARY_IDS = frozenset({"ads", "recommend", "rental"})


@dataclass(frozen=True, slots=True)
class _ImageSegment:
    natural_width: int
    natural_height: int
    complete: bool
    x: float
    y: float
    width: float
    height: float
    source_fingerprint: str = ""


@dataclass(frozen=True, slots=True)
class _BodyPage:
    index: int
    x: float
    y: float
    width: float
    height: float
    visible: bool
    partial: bool
    center_owned: bool
    segments: tuple[_ImageSegment, ...]
    perimeter_owned: bool = True


@dataclass(frozen=True, slots=True)
class _ReaderSnapshot:
    counter_text: str
    current: int
    total: int
    viewport_width: float
    viewport_height: float
    page_container_count: int
    body_pages: tuple[_BodyPage, ...]
    auxiliary_ids: tuple[str, ...]
    duplicate_indices: bool
    rental_count: int
    rental_visible: bool
    rental_presented: bool
    rental_geometry: tuple[float, float, float, float] | None
    rental_title: str | None
    rental_title_presented: bool
    rental_title_geometry: tuple[float, float, float, float] | None
    rental_next_label: str | None
    rental_next_presented: bool
    rental_next_geometry: tuple[float, float, float, float] | None
    rental_next_count: int
    access_gate_visible: bool
    next_arrow_count: int
    next_arrow_hidden: bool
    next_arrow_parent_id: str | None
    next_arrow_parent_hidden: bool
    menu_count: int = 1
    menu_hidden: bool = True
    menu_overlay_known: bool = False
    rental_signup_count: int = 0
    rental_signup_label: str | None = None
    rental_signup_path: str | None = None
    rental_signup_same_origin: bool = False
    rental_signup_forward_episode_id: str | None = None
    rental_signup_presented: bool = False
    rental_signup_geometry: tuple[float, float, float, float] | None = None

    @property
    def visible_pages(self) -> tuple[_BodyPage, ...]:
        return tuple(page for page in self.body_pages if page.visible)


def parse_yanmaga_composite_id(value: str) -> tuple[str, str] | None:
    """Parse the Catalog's `<decoded-work-slug>:<episode32hex>` identity."""

    match = _COMPOSITE_ID.fullmatch(value)
    if match is None:
        return None
    slug = match.group("slug")
    episode = match.group("episode")
    if parse_yanmaga_work_url(f"https://{SITE_HOST}/comics/{quote(slug, safe='')}") != YanmagaWorkParts(slug):
        return None
    return slug, episode


def parse_yanmaga_viewer_url(url: str) -> YanmagaEpisodeParts | None:
    """Accept the observed route with no query or its exact opaque ``cid`` field."""

    try:
        parsed = urlsplit(url)
        port = parsed.port
    except ValueError:
        return None
    if (
        parsed.scheme.lower() != "https"
        or (parsed.hostname or "").lower() != SITE_HOST
        or port not in (None, 443)
        or parsed.username is not None
        or parsed.password is not None
        or (parsed.query and _VIEWER_CID_QUERY.fullmatch(parsed.query) is None)
        or parsed.fragment
    ):
        return None
    match = _VIEWER_PATH.fullmatch(parsed.path)
    if match is None:
        return None
    source_url = urlunsplit(
        ("https", SITE_HOST, f"/comics/{match.group('slug')}/{match.group('episode')}", "", "")
    )
    return parse_yanmaga_episode_url(source_url)


def parse_yanmaga_page_counter(value: str | None) -> tuple[int, int] | None:
    match = _PAGE_COUNTER.fullmatch((value or "").strip())
    if match is None:
        return None
    current, total = int(match.group("current")), int(match.group("total"))
    return (current, total) if current <= total <= MAX_BODY_PAGES else None


def _read_snapshot_js() -> str:
    return r"""() => {
      const counterLeaves = [...document.querySelectorAll('body *')].filter(node =>
        node.children.length === 0 && /^\s*[1-9][0-9]*\s*\/\s*[1-9][0-9]*\s*$/.test(node.innerText || ''));
      const pagesRoots = [...document.querySelectorAll('.pages#content')];
      const root = pagesRoots.length === 1 ? pagesRoots[0] : null;
      const rect = node => {
        const box = node.getBoundingClientRect();
        return {x:box.x,y:box.y,width:box.width,height:box.height};
      };
      const presented = node => {
        if (!node || !visible(node)) return {presented:false,centerOwned:false,box:null};
        const box = rect(node);
        const inViewport = box.x >= -0.5 && box.y >= -0.5 &&
          box.x + box.width <= innerWidth + 0.5 && box.y + box.height <= innerHeight + 0.5;
        const center = document.elementFromPoint(box.x+box.width/2,box.y+box.height/2);
        const centerOwned = !!center && (center === node || node.contains(center));
        return {presented:inViewport && centerOwned,centerOwned,box};
      };
      const visible = node => {
        const style = getComputedStyle(node), box = rect(node);
        return style.display !== 'none' && style.visibility !== 'hidden' &&
          Number(style.opacity || '1') > 0 && box.width > 0 && box.height > 0 &&
          node.checkVisibility({checkVisibilityCSS:true,checkOpacity:true});
      };
      const children = root ? [...root.children] : [];
      const bodyNodes = children.filter(node => /^content-p[1-9][0-9]*$/.test(node.id));
      const auxiliaryIds = children.filter(node => !/^content-p[1-9][0-9]*$/.test(node.id))
        .map(node => node.id || '');
      const bodyPages = bodyNodes.map(node => {
        const box = rect(node);
        const isVisible = visible(node);
        const intersects = box.x < innerWidth && box.x + box.width > 0 &&
          box.y < innerHeight && box.y + box.height > 0;
        // Adjacent verified spread wrappers overlap by 2 CSS px; sample outside
        // that measured overlap while retaining coverage on narrow wrappers.
        const perimeterInsetPx = 4;
        const insetX = Math.min(perimeterInsetPx, box.width / 4);
        const insetY = Math.min(perimeterInsetPx, box.height / 4);
        const perimeterPoints = [
          [box.x+insetX,box.y+insetY], [box.x+box.width/2,box.y+insetY],
          [box.x+box.width-insetX,box.y+insetY],
          [box.x+insetX,box.y+box.height/2],
          [box.x+box.width-insetX,box.y+box.height/2],
          [box.x+insetX,box.y+box.height-insetY],
          [box.x+box.width/2,box.y+box.height-insetY],
          [box.x+box.width-insetX,box.y+box.height-insetY]
        ];
        return {
          id:node.id, x:box.x,y:box.y,width:box.width,height:box.height,
          visible:isVisible && intersects,
          partial:isVisible && intersects && !(box.x >= -0.5 && box.y >= -0.5 &&
            box.x + box.width <= innerWidth + 0.5 && box.y + box.height <= innerHeight + 0.5),
          segments:[...node.querySelectorAll('img')].map(image => {
            const imageBox=rect(image);
            return {naturalWidth:image.naturalWidth,naturalHeight:image.naturalHeight,
              complete:image.complete,source:image.currentSrc || image.src || '',
              x:imageBox.x,y:imageBox.y,width:imageBox.width,height:imageBox.height};
          }),
          centerOwned:(() => {
            const center = document.elementFromPoint(box.x+box.width/2,box.y+box.height/2);
            return !!center && (center === node || node.contains(center));
          })(),
          perimeterOwned:perimeterPoints.every(([x,y]) => {
            const hit = document.elementFromPoint(x,y);
            return !!hit && (hit === node || node.contains(hit));
          })
        };
      });
      const rentalNodes = root ? [...root.children].filter(node => node.id === 'rental') : [];
      const rental = rentalNodes.length === 1 ? rentalNodes[0] : null;
      const next = rental ? [...rental.querySelectorAll('#js-btn-valid-next-episode')] : [];
      const signups = rental ? [...rental.querySelectorAll(
        'a.mod-button--orange.content.ga-viewer-rental-signup')
      ] : [];
      const signup = signups.length === 1 ? signups[0] : null;
      let signupPath = null, signupSameOrigin = false, signupForwardEpisodeId = null;
      if (signup) {
        try {
          const signupUrl = new URL(signup.href, location.href);
          signupSameOrigin = signupUrl.protocol === 'https:' &&
            signupUrl.origin === location.origin && !signupUrl.username && !signupUrl.password;
          if (signupSameOrigin) {
            signupPath = signupUrl.pathname;
            const forward = /^\?forward=([0-9a-f]{32})$/.exec(signupUrl.search);
            if (signupUrl.pathname === '/customers/sign-up' && !signupUrl.hash && forward) {
              signupForwardEpisodeId = forward[1];
            }
          }
        } catch {}
      }
      const titles = rental ? [...rental.querySelectorAll('.episode-modal-eptitle')] : [];
      const title = titles.length === 1 ? titles[0] : null;
      const rentalPresentation = presented(rental);
      const titlePresentation = presented(title);
      const nextPresentation = presented(next.length === 1 ? next[0] : null);
      const signupPresentation = presented(signup);
      const menuNodes = [...document.querySelectorAll('#menu')];
      const menu = menuNodes.length === 1 ? menuNodes[0] : null;
      const menuStyle = menu ? getComputedStyle(menu) : null;
      const menuBox = menu ? rect(menu) : null;
      const headerNodes = [...document.querySelectorAll('#menu_header')];
      const controllerNodes = [...document.querySelectorAll('#menu_controller')];
      const transparentNodes = [...document.querySelectorAll('#menu_transparent')];
      const menuHidden = menuNodes.length === 1 && !!menuStyle && !!menuBox &&
        menuStyle.display === 'none' && menuBox.width === 0 && menuBox.height === 0;
      const menuOverlayKnown = menuNodes.length === 1 && !!menu && visible(menu) &&
        !!menuBox && menuBox.x <= 0 && menuBox.y <= 0 &&
        menuBox.width >= innerWidth && menuBox.height >= innerHeight &&
        headerNodes.length === 1 && visible(headerNodes[0]) &&
        controllerNodes.length === 1 && visible(controllerNodes[0]) &&
        transparentNodes.length === 1 && visible(transparentNodes[0]);
      const arrowNodes = [...document.querySelectorAll('.arrow-next-page')];
      const arrow = arrowNodes.length === 1 ? arrowNodes[0] : null;
      const arrowStyle = arrow ? getComputedStyle(arrow) : null;
      const arrowBox = arrow ? rect(arrow) : null;
      const accessGateVisible = [...document.querySelectorAll(
        '[role="dialog"],[aria-modal="true"],dialog,[class*="modal" i],[class*="alert" i]')]
        .filter(visible).some(node => /初回無料|チケット|ポイント|レンタル|購入|ログイン|会員登録|無料は1日で読める数/.test(
          (node.innerText || '').replace(/\s+/g,' ').trim()));
      return {
        counterCount:counterLeaves.length,
        counterText:counterLeaves.length === 1 ? (counterLeaves[0].innerText || '').trim() : '',
        pageContainerCount:pagesRoots.length,
        viewportWidth:innerWidth,viewportHeight:innerHeight,
        bodyPages,
        auxiliaryIds,
        duplicateIndices:new Set(bodyPages.map(page => page.id)).size !== bodyPages.length,
        rentalCount:rentalNodes.length,
        rentalVisible:!!rental && visible(rental),
        rentalPresented:rentalPresentation.presented,
        rentalGeometry:rentalPresentation.box,
        rentalTitle:title?.innerText?.trim() || null,
        rentalTitlePresented:titlePresentation.presented,
        rentalTitleGeometry:titlePresentation.box,
        rentalNextLabel:next.length === 1 ? (next[0].innerText || '').replace(/\s+/g,' ').trim() : null,
        rentalNextCount:next.length,
        rentalNextPresented:nextPresentation.presented,
        rentalNextGeometry:nextPresentation.box,
        rentalSignupCount:signups.length,
        rentalSignupLabel:signup ? (signup.innerText || '').replace(/\s+/g,' ').trim() : null,
        rentalSignupPath:signupPath,
        rentalSignupSameOrigin:signupSameOrigin,
        rentalSignupForwardEpisodeId:signupForwardEpisodeId,
        rentalSignupPresented:signupPresentation.presented,
        rentalSignupGeometry:signupPresentation.box,
        menuCount:menuNodes.length,
        menuHidden,
        menuOverlayKnown,
        accessGateVisible,
        nextArrowCount:arrowNodes.length,
        nextArrowHidden:!!arrow && !!arrowStyle &&
          (arrowStyle.visibility === 'hidden' || arrowStyle.display === 'none') &&
          !!arrowBox && arrowBox.width === 0 && arrowBox.height === 0,
        nextArrowParentId:arrow?.parentElement?.id || null,
        nextArrowParentHidden:!!arrow?.parentElement?.classList.contains('hide')
      };
    }"""


class YanmagaAdapter(SiteAdapter):
    """Capture the exact currently-free Yanmaga episode as rendered page PNGs."""

    page_change_timeout_ms = PAGE_CHANGE_TIMEOUT_MS

    def __init__(self) -> None:
        self._access_strategy: AccessStrategy = "auto"
        self._expected: YanmagaEpisodeParts | None = None
        self._expected_external_id: str | None = None
        self._work_key: str | None = None
        self._source_url: str | None = None
        self._work_url: str | None = None
        self._viewer_url: str | None = None
        self._listing_rows: tuple[YanmagaListingRow, ...] | None = None
        self._work_title: str | None = None
        self._episode_title: str | None = None
        self._total_pages: int | None = None
        self._captured_indices: list[int] = []
        self._advance_pending = False
        self._ended = False
        self._listing_rows = None

    def get_access_profile(self) -> AccessProfile:
        return yanmaga_access_profile()

    def get_initialize_timeout_ms(self, default_ms: int) -> int:
        del default_ms
        return INITIALIZE_TIMEOUT_MS

    async def configure_run(self, page: Page, access_strategy: AccessStrategy) -> None:
        del page
        if access_strategy not in {"auto", "direct"}:
            raise UnsupportedAccessStrategyError(
                "Yanmaga free capture supports access_strategy='auto' or 'direct' only"
            )
        self._access_strategy = access_strategy

    async def configure_quota_resource(
        self, page: Page, quota_resource: str | None
    ) -> None:
        del page
        if quota_resource is not None:
            raise UnsupportedAccessStrategyError(
                "Yanmaga does not support quota or resource-based access"
            )

    async def configure_target_identity(self, external_id: str, work_key: str) -> None:
        parsed = parse_yanmaga_composite_id(external_id)
        if parsed is None:
            raise UnknownPageStateError("Yanmaga Catalog identity is malformed")
        slug, episode_id = parsed
        self._expected = YanmagaEpisodeParts(slug, episode_id)
        self._expected_external_id = external_id
        self._work_key = work_key

    def resolve_initial_navigation_url(self, source_url: str) -> str:
        requested = parse_yanmaga_episode_url(source_url)
        if requested is None:
            raise UnknownPageStateError("Yanmaga crawl requires the canonical public episode URL")
        if self._expected is not None and requested != self._expected:
            raise UnknownPageStateError("Yanmaga source URL differs from the configured Catalog target")
        if self._expected_external_id is not None and self._expected_external_id != (
            f"{requested.slug}:{requested.episode_id}"
        ):
            raise UnknownPageStateError(
                "Yanmaga source URL differs from the configured Catalog identity"
            )
        self._expected = requested
        self._expected_external_id = f"{requested.slug}:{requested.episode_id}"
        self._work_key = self._work_key or f"yanmaga:{requested.slug}"
        self._source_url = source_url
        self._work_url = f"https://{SITE_HOST}/comics/{quote(requested.slug, safe='')}"
        return self._work_url

    async def initialize(self, page: Page) -> None:
        expected = self._require_expected()
        if self._source_url is None or self._work_url is None:
            raise UnknownPageStateError("Yanmaga target URL was not resolved before navigation")
        if parse_yanmaga_work_url(page.url) != YanmagaWorkParts(expected.slug):
            raise UnknownPageStateError("Yanmaga preflight did not land on the requested work page")

        await page.set_viewport_size({"width": VIEWPORT_WIDTH, "height": VIEWPORT_HEIGHT})
        self._captured_indices.clear()
        self._total_pages = None
        self._advance_pending = False
        self._ended = False

        target = WatchlistTarget(
            key=f"yanmaga-preflight-{expected.episode_id}",
            work_key=self._work_key or f"yanmaga:{expected.slug}",
            site="yanmaga",
            url=self._work_url,
            label=expected.slug,
        )
        discovery = YanmagaDiscoveryAdapter()
        records = [record async for record in discovery.iter_records(page, target, "full")]
        listing = discovery.last_snapshot
        if listing is None or not listing.anonymous:
            raise UnknownPageStateError(
                "Yanmaga current public listing lacks explicit anonymous-state proof"
            )
        self._listing_rows = listing.rows
        matches = [
            record
            for record in records
            if record.source.external_id == f"{expected.slug}:{expected.episode_id}"
        ]
        if not matches:
            raise AccessResourceUnavailableError(
                "yanmaga_target_not_in_current_public_listing"
            )
        if len(matches) != 1:
            raise UnknownPageStateError("Yanmaga target episode is duplicated in the live listing")
        match = matches[0]
        row_matches = [row for row in listing.rows if row.episode_id == expected.episode_id]
        if len(row_matches) != 1:
            raise UnknownPageStateError("Yanmaga target row is absent from the validated listing snapshot")
        row = row_matches[0]
        if match.source.access_mode != "free":
            if row.known_restricted and not row.red_marker_present:
                raise AccessResourceUnavailableError(
                    "yanmaga_target_no_longer_unconditionally_free"
                )
            raise UnknownPageStateError(
                "Yanmaga target lacks unambiguous current anonymous free evidence"
            )
        if not row.free_marker or match.source.url != self._source_url:
            raise UnknownPageStateError("Yanmaga free listing route differs from the requested source URL")
        self._work_title = match.item.canonical_title or expected.slug
        self._episode_title = match.item.order_label
        if not self._episode_title:
            raise UnknownPageStateError("Yanmaga target episode label is unavailable")

        await page.goto(self._source_url, wait_until="domcontentloaded", timeout=30_000)
        self._validate_viewer_route(page)
        snapshot = await self._wait_for_stable_snapshot(
            page,
            timeout_ms=PAGE_CHANGE_TIMEOUT_MS,
            allow_known_menu_overlay=True,
        )
        self._total_pages = snapshot.total
        self._validate_snapshot(snapshot, allow_known_menu_overlay=True)
        first = await self._rewind_to_first(
            page, snapshot, allow_known_menu_overlay=True
        )
        if first.current != 1 or not any(item.index == 1 for item in first.visible_pages):
            raise UnknownPageStateError("Yanmaga viewer did not restore its first body page")
        first = await self._prepare_first_page_capture(page, first)
        self._viewer_url = page.url

    def _require_expected(self) -> YanmagaEpisodeParts:
        if self._expected is None:
            raise UnknownPageStateError("Yanmaga target identity is incomplete")
        return self._expected

    def _validate_viewer_route(self, page: Page) -> None:
        expected = self._require_expected()
        current = parse_yanmaga_viewer_url(page.url)
        if current != expected:
            raise UnknownPageStateError("Yanmaga redirected outside the requested viewer episode")

    async def _read_snapshot(self, page: Page) -> _ReaderSnapshot | None:
        try:
            raw = await page.main_frame.evaluate(_read_snapshot_js())
        except (PlaywrightError, TypeError, ValueError) as exc:
            raise UnknownPageStateError("Yanmaga reader state could not be inspected") from exc
        if not isinstance(raw, dict):
            raise UnknownPageStateError("Yanmaga reader state is malformed")
        counter = parse_yanmaga_page_counter(raw.get("counterText"))
        if (
            raw.get("counterCount") != 1
            or counter is None
            or raw.get("pageContainerCount") != 1
        ):
            return None
        current, total = counter
        raw_pages = raw.get("bodyPages")
        if not isinstance(raw_pages, list):
            raise UnknownPageStateError("Yanmaga native body page list is malformed")
        raw_auxiliary = raw.get("auxiliaryIds")
        if not isinstance(raw_auxiliary, list) or any(
            not isinstance(value, str) for value in raw_auxiliary
        ):
            raise UnknownPageStateError("Yanmaga auxiliary reader roles are malformed")
        pages: list[_BodyPage] = []
        seen: set[int] = set()
        duplicate_indices = raw.get("duplicateIndices") is True
        for raw_page in raw_pages:
            if not isinstance(raw_page, dict) or not isinstance(raw_page.get("id"), str):
                raise UnknownPageStateError("Yanmaga native page wrapper is malformed")
            match = _PAGE_ID.fullmatch(raw_page["id"])
            if match is None:
                raise UnknownPageStateError("Yanmaga native page wrapper identity is unsupported")
            index = int(match.group("index"))
            if index > total or index in seen:
                duplicate_indices = True
            seen.add(index)
            segments_value = raw_page.get("segments")
            if not isinstance(segments_value, list):
                raise UnknownPageStateError("Yanmaga image segment list is malformed")
            segments: list[_ImageSegment] = []
            for raw_segment in segments_value:
                if not isinstance(raw_segment, dict):
                    raise UnknownPageStateError("Yanmaga image segment metadata is malformed")
                try:
                    source = raw_segment["source"]
                    if not isinstance(source, str) or not source:
                        raise ValueError("image source is absent")
                    segments.append(
                        _ImageSegment(
                            natural_width=int(raw_segment["naturalWidth"]),
                            natural_height=int(raw_segment["naturalHeight"]),
                            complete=raw_segment.get("complete") is True,
                            x=float(raw_segment["x"]),
                            y=float(raw_segment["y"]),
                            width=float(raw_segment["width"]),
                            height=float(raw_segment["height"]),
                            source_fingerprint=sha256(source.encode("utf-8")).hexdigest(),
                        )
                    )
                except (KeyError, TypeError, ValueError, OverflowError) as exc:
                    raise UnknownPageStateError(
                        "Yanmaga image segment metadata is incomplete"
                    ) from exc
            try:
                pages.append(
                    _BodyPage(
                        index=index,
                        x=float(raw_page["x"]),
                        y=float(raw_page["y"]),
                        width=float(raw_page["width"]),
                        height=float(raw_page["height"]),
                        visible=raw_page.get("visible") is True,
                        partial=raw_page.get("partial") is True,
                        center_owned=raw_page.get("centerOwned") is True,
                        segments=tuple(segments),
                        perimeter_owned=raw_page.get("perimeterOwned") is True,
                    )
                )
            except (KeyError, TypeError, ValueError, OverflowError) as exc:
                raise UnknownPageStateError("Yanmaga native page geometry is malformed") from exc
        for field in (
            "rentalCount",
            "rentalNextCount",
            "rentalSignupCount",
            "nextArrowCount",
            "pageContainerCount",
            "menuCount",
        ):
            if isinstance(raw.get(field), bool) or not isinstance(raw.get(field), int):
                raise UnknownPageStateError("Yanmaga terminal marker metadata is malformed")

        def geometry(field: str) -> tuple[float, float, float, float] | None:
            value = raw.get(field)
            if not isinstance(value, dict):
                return None
            try:
                values = tuple(float(value[key]) for key in ("x", "y", "width", "height"))
            except (KeyError, TypeError, ValueError, OverflowError):
                return None
            if not all(isfinite(part) for part in values) or values[2] <= 0 or values[3] <= 0:
                return None
            return values  # type: ignore[return-value]

        return _ReaderSnapshot(
            counter_text=str(raw.get("counterText") or ""),
            current=current,
            total=total,
            viewport_width=float(raw.get("viewportWidth") or 0),
            viewport_height=float(raw.get("viewportHeight") or 0),
            page_container_count=int(raw["pageContainerCount"]),
            body_pages=tuple(pages),
            auxiliary_ids=tuple(raw_auxiliary),
            duplicate_indices=duplicate_indices,
            rental_count=int(raw["rentalCount"]),
            rental_visible=raw.get("rentalVisible") is True,
            rental_presented=raw.get("rentalPresented") is True,
            rental_geometry=geometry("rentalGeometry"),
            rental_title=raw.get("rentalTitle") if isinstance(raw.get("rentalTitle"), str) else None,
            rental_title_presented=raw.get("rentalTitlePresented") is True,
            rental_title_geometry=geometry("rentalTitleGeometry"),
            rental_next_label=raw.get("rentalNextLabel") if isinstance(raw.get("rentalNextLabel"), str) else None,
            rental_next_presented=raw.get("rentalNextPresented") is True,
            rental_next_geometry=geometry("rentalNextGeometry"),
            rental_next_count=int(raw["rentalNextCount"]),
            access_gate_visible=raw.get("accessGateVisible") is True,
            next_arrow_count=int(raw["nextArrowCount"]),
            next_arrow_hidden=raw.get("nextArrowHidden") is True,
            next_arrow_parent_id=raw.get("nextArrowParentId") if isinstance(raw.get("nextArrowParentId"), str) else None,
            next_arrow_parent_hidden=raw.get("nextArrowParentHidden") is True,
            menu_count=int(raw["menuCount"]),
            menu_hidden=raw.get("menuHidden") is True,
            menu_overlay_known=raw.get("menuOverlayKnown") is True,
            rental_signup_count=int(raw["rentalSignupCount"]),
            rental_signup_label=(
                raw.get("rentalSignupLabel")
                if isinstance(raw.get("rentalSignupLabel"), str)
                else None
            ),
            rental_signup_path=(
                raw.get("rentalSignupPath")
                if isinstance(raw.get("rentalSignupPath"), str)
                else None
            ),
            rental_signup_same_origin=raw.get("rentalSignupSameOrigin") is True,
            rental_signup_forward_episode_id=(
                raw.get("rentalSignupForwardEpisodeId")
                if isinstance(raw.get("rentalSignupForwardEpisodeId"), str)
                else None
            ),
            rental_signup_presented=raw.get("rentalSignupPresented") is True,
            rental_signup_geometry=geometry("rentalSignupGeometry"),
        )

    def _validate_snapshot(
        self,
        snapshot: _ReaderSnapshot,
        *,
        allow_known_menu_overlay: bool = False,
    ) -> tuple[int, ...]:
        if self._total_pages is not None and snapshot.total != self._total_pages:
            raise UnknownPageStateError("Yanmaga viewer page total changed during capture")
        if snapshot.duplicate_indices:
            raise UnknownPageStateError("Yanmaga viewer has duplicate or out-of-range body page IDs")
        if snapshot.access_gate_visible:
            raise UnknownPageStateError("Yanmaga viewer shows a login, quota or resource gate")
        if len(set(snapshot.auxiliary_ids)) != len(snapshot.auxiliary_ids) or any(
            auxiliary not in _ALLOWED_AUXILIARY_IDS and _BANNER_ID.fullmatch(auxiliary) is None
            for auxiliary in snapshot.auxiliary_ids
        ):
            raise UnknownPageStateError("Yanmaga reader contains an unsupported auxiliary role")
        if snapshot.viewport_width < VIEWPORT_WIDTH or snapshot.viewport_height < VIEWPORT_HEIGHT:
            raise UnknownPageStateError("Yanmaga viewer capture viewport is below the verified size")
        if snapshot.menu_count != 1:
            raise UnknownPageStateError("Yanmaga reader menu identity is absent or duplicated")
        overlay_pages = (
            (snapshot.current == 1 and tuple(page.index for page in snapshot.visible_pages) == (1,))
            or (snapshot.current == 2 and tuple(page.index for page in snapshot.visible_pages) == (2, 3))
        )
        tolerate_menu = (
            allow_known_menu_overlay
            and snapshot.menu_overlay_known
            and overlay_pages
        )
        if not tolerate_menu and not snapshot.menu_hidden:
            raise UnknownPageStateError("Yanmaga reader menu is not proven hidden for capture")
        visible = snapshot.visible_pages
        if not visible or len(visible) > 2:
            raise UnknownPageStateError("Yanmaga viewer has an unsupported visible body-page group")
        for page in visible:
            if page.partial or (not tolerate_menu and not page.center_owned):
                raise UnknownPageStateError(
                    "Yanmaga body page is clipped or obstructed by another reader element "
                    f"(partial={page.partial}, center_owned={page.center_owned}, "
                    f"box=({page.x},{page.y},{page.width},{page.height}), "
                    f"viewport=({snapshot.viewport_width},{snapshot.viewport_height}))"
                )
            if not tolerate_menu and not page.perimeter_owned:
                raise UnknownPageStateError(
                    "Yanmaga body page perimeter is obstructed by another reader element"
                )
            if (
                page.x < -0.5
                or page.y < -0.5
                or page.x + page.width > snapshot.viewport_width + 0.5
                or page.y + page.height > snapshot.viewport_height + 0.5
            ):
                raise UnknownPageStateError("Yanmaga body page wrapper is clipped by the viewport")
            if not self._segments_form_observed_page(page):
                raise UnknownPageStateError(
                    "Yanmaga body page is not the verified three-segment rendered wrapper"
                )
        indices = tuple(sorted(page.index for page in visible))
        if len(set(indices)) != len(indices):
            raise UnknownPageStateError("Yanmaga visible body page IDs are duplicated")
        if len(indices) == 2 and indices[1] != indices[0] + 1:
            raise UnknownPageStateError("Yanmaga visible spread is not a contiguous page pair")
        return indices

    @staticmethod
    def _segments_form_observed_page(page: _BodyPage) -> bool:
        if (
            len(page.segments) != 3
            or not all(isfinite(value) for value in (page.x, page.y, page.width, page.height))
            or page.width <= 0
            or page.height <= 0
        ):
            return False
        segments = page.segments
        widths = {segment.natural_width for segment in segments}
        if (
            len(widths) != 1
            or next(iter(widths), 0) <= 0
            or any(
                not segment.complete
                or segment.natural_width <= 0
                or segment.natural_height <= 0
                or not all(
                    isfinite(value)
                    for value in (segment.x, segment.y, segment.width, segment.height)
                )
                or segment.width <= 0
                or segment.height <= 0
                or not segment.source_fingerprint
                for segment in segments
            )
        ):
            return False
        if (
            abs(segments[0].x - page.x) > SEGMENT_EDGE_TOLERANCE_PX
            or abs(segments[0].y - page.y) > 1
        ):
            return False
        if any(
            abs(segment.x - page.x) > SEGMENT_EDGE_TOLERANCE_PX
            or abs(
                segment.x
                + segment.width
                - page.x
                - page.width
            )
            > SEGMENT_EDGE_TOLERANCE_PX
            for segment in segments
        ):
            return False
        for previous, following in pairwise(segments):
            previous_bottom = previous.y + previous.height
            overlap = previous_bottom - following.y
            if following.y > previous_bottom + 1 or following.y <= previous.y or overlap > 8:
                return False
        final_bottom = segments[-1].y + segments[-1].height
        page_bottom = page.y + page.height
        return (
            page_bottom - FINAL_SEGMENT_BOTTOM_UNDERFLOW_PX
            <= final_bottom
            <= page_bottom + FINAL_SEGMENT_BOTTOM_OVERFLOW_PX
        )

    @staticmethod
    def _snapshot_signature(snapshot: _ReaderSnapshot) -> tuple[object, ...]:
        return (
            snapshot.current,
            snapshot.total,
            tuple(
                (
                    page.index,
                    round(page.x, 1),
                    round(page.y, 1),
                    round(page.width, 1),
                    round(page.height, 1),
                    page.partial,
                    page.center_owned,
                    page.perimeter_owned,
                    tuple(
                        (
                            segment.natural_width,
                            segment.natural_height,
                            segment.complete,
                            segment.source_fingerprint,
                            round(segment.x, 1),
                            round(segment.y, 1),
                            round(segment.width, 1),
                            round(segment.height, 1),
                        )
                        for segment in page.segments
                    ),
                )
                for page in snapshot.visible_pages
            ),
            snapshot.auxiliary_ids,
            snapshot.rental_visible,
            snapshot.rental_presented,
            snapshot.rental_geometry,
            snapshot.rental_title,
            snapshot.rental_title_presented,
            snapshot.rental_title_geometry,
            snapshot.rental_next_label,
            snapshot.rental_next_presented,
            snapshot.rental_next_geometry,
            snapshot.rental_next_count,
            snapshot.rental_signup_label,
            snapshot.rental_signup_path,
            snapshot.rental_signup_same_origin,
            snapshot.rental_signup_forward_episode_id,
            snapshot.rental_signup_presented,
            snapshot.rental_signup_geometry,
            snapshot.rental_signup_count,
            snapshot.menu_count,
            snapshot.menu_hidden,
            snapshot.menu_overlay_known,
            snapshot.access_gate_visible,
        )

    async def _wait_for_stable_snapshot(
        self,
        page: Page,
        *,
        timeout_ms: int,
        allow_known_menu_overlay: bool = False,
    ) -> _ReaderSnapshot:
        deadline = monotonic() + timeout_ms / 1000
        last_signature: tuple[object, ...] | None = None
        last_validation_error: str | None = None
        stable_reads = 0
        while monotonic() < deadline:
            self._validate_viewer_route(page)
            snapshot = await self._read_snapshot(page)
            if snapshot is not None:
                try:
                    self._validate_snapshot(
                        snapshot,
                        allow_known_menu_overlay=allow_known_menu_overlay,
                    )
                except UnknownPageStateError as exc:
                    last_validation_error = str(exc)
                    await page.wait_for_timeout(RENDER_POLL_MS)
                    continue
                signature = self._snapshot_signature(snapshot)
                if signature == last_signature:
                    stable_reads += 1
                else:
                    last_signature = signature
                    stable_reads = 1
                if stable_reads >= STABLE_READS_REQUIRED:
                    return snapshot
            else:
                last_signature = None
                stable_reads = 0
            await page.wait_for_timeout(RENDER_POLL_MS)
        reason = f": {last_validation_error}" if last_validation_error else ""
        raise PageChangeTimeoutError(
            f"Yanmaga rendered body pages did not stabilize{reason}"
        )

    async def _wait_for_positive_terminal(
        self, page: Page, *, timeout_ms: int
    ) -> _ReaderSnapshot:
        deadline = monotonic() + timeout_ms / 1000
        last_signature: tuple[object, ...] | None = None
        stable_reads = 0
        while monotonic() < deadline:
            self._validate_viewer_route(page)
            snapshot = await self._read_snapshot(page)
            if snapshot is not None:
                self._validate_snapshot(snapshot)
                if self._is_positive_terminal(snapshot):
                    signature = self._snapshot_signature(snapshot)
                    stable_reads = stable_reads + 1 if signature == last_signature else 1
                    if stable_reads >= STABLE_READS_REQUIRED:
                        return snapshot
                    last_signature = signature
                else:
                    last_signature = None
                    stable_reads = 0
            else:
                last_signature = None
                stable_reads = 0
            await page.wait_for_timeout(RENDER_POLL_MS)
        raise UnknownPageStateError(
            "Yanmaga final body lacks a stable, verified terminal boundary"
        )

    async def _rewind_to_first(
        self,
        page: Page,
        snapshot: _ReaderSnapshot,
        *,
        allow_known_menu_overlay: bool = False,
    ) -> _ReaderSnapshot:
        for _ in range(MAX_REWIND_TURNS):
            if snapshot.current == 1:
                return snapshot
            previous = snapshot.current
            await page.keyboard.press("ArrowRight")
            deadline = monotonic() + PAGE_CHANGE_TIMEOUT_MS / 1000
            moved: _ReaderSnapshot | None = None
            while monotonic() < deadline:
                await page.wait_for_timeout(RENDER_POLL_MS)
                candidate = await self._read_snapshot(page)
                if candidate is None or candidate.current == previous:
                    continue
                if candidate.total != snapshot.total or candidate.current >= previous:
                    raise UnknownPageStateError("Yanmaga previous-page action changed reader identity")
                moved = await self._wait_for_stable_snapshot(
                    page,
                    timeout_ms=PAGE_CHANGE_TIMEOUT_MS,
                    allow_known_menu_overlay=allow_known_menu_overlay,
                )
                break
            if moved is None:
                raise PageChangeTimeoutError("Yanmaga reader could not return to its first page")
            snapshot = moved
        raise PageChangeTimeoutError("Yanmaga first-page rewind exceeded its turn bound")

    @staticmethod
    def _first_page_capture_is_clear(snapshot: _ReaderSnapshot) -> bool:
        return (
            snapshot.menu_count == 1
            and snapshot.menu_hidden
            and any(item.index == 1 for item in snapshot.visible_pages)
            and all(item.perimeter_owned for item in snapshot.visible_pages)
        )

    async def _wait_for_clear_first_page(
        self, page: Page, *, expected_total: int
    ) -> _ReaderSnapshot:
        deadline = monotonic() + PAGE_CHANGE_TIMEOUT_MS / 1000
        last_signature: tuple[object, ...] | None = None
        stable_reads = 0
        while monotonic() < deadline:
            self._validate_viewer_route(page)
            snapshot = await self._read_snapshot(page)
            if snapshot is not None:
                if snapshot.total != expected_total or snapshot.current != 1:
                    raise UnknownPageStateError(
                        "Yanmaga UI cleanup changed the current episode page identity"
                    )
                self._validate_snapshot(snapshot)
                if self._first_page_capture_is_clear(snapshot):
                    signature = self._snapshot_signature(snapshot)
                    stable_reads = stable_reads + 1 if signature == last_signature else 1
                    last_signature = signature
                    if stable_reads >= STABLE_READS_REQUIRED:
                        return snapshot
                else:
                    stable_reads = 0
                    last_signature = None
            else:
                stable_reads = 0
                last_signature = None
            await page.wait_for_timeout(RENDER_POLL_MS)
        raise PageChangeTimeoutError(
            "Yanmaga native reader menu did not hide around the first body page"
        )

    async def _prepare_first_page_capture(
        self, page: Page, first: _ReaderSnapshot
    ) -> _ReaderSnapshot:
        if first.current != 1 or not any(item.index == 1 for item in first.visible_pages):
            raise UnknownPageStateError("Yanmaga UI cleanup requires the first native body page")
        if self._first_page_capture_is_clear(first):
            return await self._wait_for_clear_first_page(page, expected_total=first.total)
        if first.menu_count != 1 or not first.menu_overlay_known:
            raise UnknownPageStateError(
                "Yanmaga first page is obstructed by an unsupported reader overlay"
            )
        if first.total <= 1:
            raise UnknownPageStateError(
                "Yanmaga first-page reader menu cannot be hidden without a next body page"
            )

        self._validate_viewer_route(page)
        await page.keyboard.press("ArrowLeft")
        deadline = monotonic() + PAGE_CHANGE_TIMEOUT_MS / 1000
        advanced: _ReaderSnapshot | None = None
        while monotonic() < deadline:
            self._validate_viewer_route(page)
            candidate = await self._read_snapshot(page)
            if candidate is not None and candidate.current != first.current:
                if candidate.total != first.total or candidate.current != 2:
                    raise UnknownPageStateError(
                        "Yanmaga normal UI-hide turn changed the observed page sequence"
                    )
                advanced = await self._wait_for_stable_snapshot(
                    page,
                    timeout_ms=max(1, int((deadline - monotonic()) * 1000)),
                    allow_known_menu_overlay=True,
                )
                if advanced.current != 2 or advanced.total != first.total:
                    raise UnknownPageStateError(
                        "Yanmaga normal UI-hide turn did not stabilize on body page 2"
                    )
                break
            await page.wait_for_timeout(RENDER_POLL_MS)
        if advanced is None:
            raise PageChangeTimeoutError(
                "Yanmaga normal UI-hide turn did not advance to native body page 2"
            )

        restored = await self._rewind_to_first(
            page, advanced, allow_known_menu_overlay=True
        )
        if restored.current != 1 or restored.total != first.total:
            raise UnknownPageStateError(
                "Yanmaga normal UI-hide turn did not restore the first body page"
            )
        return await self._wait_for_clear_first_page(page, expected_total=first.total)

    def _is_positive_terminal(self, snapshot: _ReaderSnapshot) -> bool:
        expected = self._require_expected()
        if self._captured_indices != list(range(1, snapshot.total + 1)):
            return False
        if (
            snapshot.current != snapshot.total
            or snapshot.rental_count != 1
            or snapshot.menu_count != 1
            or not snapshot.menu_hidden
        ):
            return False
        if (
            not snapshot.rental_visible
            or not snapshot.rental_presented
            or snapshot.rental_geometry is None
            or not snapshot.rental_title
            or not snapshot.rental_title_presented
            or snapshot.rental_title_geometry is None
        ):
            return False
        valid_next = (
            snapshot.rental_next_count == 1
            and snapshot.rental_next_label == "次の話を読む"
            and snapshot.rental_next_presented
            and snapshot.rental_next_geometry is not None
            and snapshot.rental_signup_count == 0
        )
        registration_boundary = (
            snapshot.rental_next_count == 0
            and snapshot.rental_signup_count == 1
            and snapshot.rental_signup_label == "無料登録して読む"
            and snapshot.rental_signup_same_origin
            and snapshot.rental_signup_path == "/customers/sign-up"
            and self._signup_forward_matches_immediate_next_row(snapshot)
            and snapshot.rental_signup_presented
            and snapshot.rental_signup_geometry is not None
        )
        if not (valid_next or registration_boundary):
            return False
        terminal_page = [page for page in snapshot.visible_pages if page.index == snapshot.total]
        if (
            len(terminal_page) != 1
            or not terminal_page[0].center_owned
            or not terminal_page[0].perimeter_owned
        ):
            return False
        if any(page.index > snapshot.total for page in snapshot.body_pages):
            return False
        return (
            self._viewer_url is None
            or parse_yanmaga_viewer_url(self._viewer_url) == expected
        )

    def _signup_forward_matches_immediate_next_row(
        self, snapshot: _ReaderSnapshot
    ) -> bool:
        rows = self._listing_rows
        forward_id = snapshot.rental_signup_forward_episode_id
        if rows is None or re.fullmatch(r"[0-9a-f]{32}", forward_id or "") is None:
            return False
        expected = self._require_expected()
        current_indices = [
            index for index, row in enumerate(rows) if row.episode_id == expected.episode_id
        ]
        if len(current_indices) != 1:
            return False
        next_index = current_indices[0] + 1
        if next_index >= len(rows):
            return False
        next_row = rows[next_index]
        next_route = parse_yanmaga_episode_url(next_row.url)
        return (
            sum(row.episode_id == forward_id for row in rows) == 1
            and next_row.episode_id == forward_id
            and next_route is not None
            and next_route.slug == expected.slug
            and next_route.episode_id == forward_id
            and snapshot.rental_title is not None
            and " ".join(snapshot.rental_title.split()) == next_row.title
        )

    async def detect_state(self, page: Page) -> PageState:
        if self._ended:
            return PageState.END
        self._validate_viewer_route(page)
        snapshot = await self._read_snapshot(page)
        if snapshot is None:
            return PageState.LOADING if self._advance_pending else PageState.UNKNOWN
        if self._total_pages is None:
            raise UnknownPageStateError("Yanmaga reader was not initialized")
        self._validate_snapshot(snapshot)
        if snapshot.current == snapshot.total and self._captured_indices == list(
            range(1, snapshot.total + 1)
        ):
            await self._wait_for_positive_terminal(page, timeout_ms=PAGE_CHANGE_TIMEOUT_MS)
            self._ended = True
            return PageState.END
        visible_indices = tuple(sorted(page.index for page in snapshot.visible_pages))
        if any(index not in self._captured_indices for index in visible_indices):
            return PageState.CONTENT
        if self._advance_pending:
            return PageState.LOADING
        raise UnknownPageStateError("Yanmaga viewer has no uncaptured body page")

    async def get_capture_target(self, page: Page) -> Locator:
        targets = await self.get_capture_targets(page)
        if len(targets) != 1:
            raise UnknownPageStateError("Yanmaga screen is a spread; use all capture targets")
        return targets[0]

    async def get_capture_targets(self, page: Page) -> tuple[Locator, ...]:
        self._validate_viewer_route(page)
        snapshot = await self._read_snapshot(page)
        if snapshot is None:
            raise PageChangeTimeoutError("Yanmaga reader state is not ready for capture")
        visible_indices = self._validate_snapshot(snapshot)
        new_indices = tuple(index for index in visible_indices if index not in self._captured_indices)
        if not new_indices:
            raise UnknownPageStateError("Yanmaga screen contains no new body pages")
        next_expected = len(self._captured_indices) + 1
        if new_indices[0] != next_expected or new_indices != tuple(
            range(new_indices[0], new_indices[-1] + 1)
        ):
            raise UnknownPageStateError("Yanmaga body page sequence has a gap or regression")
        targets = tuple(page.locator(f"#content-p{index}") for index in new_indices)
        for target in targets:
            if await target.count() != 1:
                raise UnknownPageStateError("Yanmaga body page wrapper is absent or duplicated")
        return targets

    async def capture_page(self, page: Page) -> tuple[CaptureResult, ...] | None:
        targets = await self.get_capture_targets(page)
        snapshot = await self._wait_for_stable_snapshot(
            page, timeout_ms=PAGE_CHANGE_TIMEOUT_MS
        )
        by_index = {item.index: item for item in snapshot.visible_pages}
        target_indices_list: list[int] = []
        for target in targets:
            match = _PAGE_ID.fullmatch((await target.get_attribute("id")) or "")
            if match is None:
                raise UnknownPageStateError("Yanmaga capture target lost its native page ID")
            target_indices_list.append(int(match.group("index")))
        target_indices = tuple(target_indices_list)
        current_new_indices = tuple(
            index for index in self._validate_snapshot(snapshot) if index not in self._captured_indices
        )
        if target_indices != current_new_indices:
            raise UnknownPageStateError("Yanmaga visible page group changed before capture")
        captures: list[CaptureResult] = []
        captured_now: list[int] = []
        for target in targets:
            match = _PAGE_ID.fullmatch((await target.get_attribute("id")) or "")
            if match is None:
                raise UnknownPageStateError("Yanmaga capture target lost its native page ID")
            index = int(match.group("index"))
            proof = by_index.get(index)
            if proof is None or not proof.visible or proof.partial or not proof.center_owned:
                raise UnknownPageStateError("Yanmaga rendered page visibility proof changed before capture")
            if not self._segments_form_observed_page(proof):
                raise UnknownPageStateError("Yanmaga rendered page proof changed before capture")
            result = await capture_locator(target)
            natural_width = max(segment.natural_width for segment in proof.segments)
            if result.width is None or result.height is None or result.width < natural_width:
                raise UnknownPageStateError(
                    "Yanmaga rendered page capture is below the verified source-segment width"
                )
            captures.append(result)
            captured_now.append(index)
        if captured_now != list(range(len(self._captured_indices) + 1, len(self._captured_indices) + 1 + len(captured_now))):
            raise UnknownPageStateError("Yanmaga capture buffer is not sequential")
        after = await self._wait_for_stable_snapshot(
            page, timeout_ms=PAGE_CHANGE_TIMEOUT_MS
        )
        if self._snapshot_signature(after) != self._snapshot_signature(snapshot):
            raise UnknownPageStateError("Yanmaga reader changed while rendered pages were captured")
        self._captured_indices.extend(captured_now)
        return tuple(captures)

    async def get_content_identity(self, page: Page) -> ContentIdentity:
        self._validate_viewer_route(page)
        snapshot = await self._read_snapshot(page)
        if snapshot is None:
            raise PageChangeTimeoutError("Yanmaga reader identity is not ready")
        visible_indices = self._validate_snapshot(snapshot)
        page_ids = tuple(f"content-p{index}" for index in visible_indices)
        return ContentIdentity(
            page_id="|".join(page_ids),
            page_number=snapshot.current,
            source_id=self._expected_external_id,
        )

    async def get_content_context(self, page: Page) -> ContentContext:
        self._validate_viewer_route(page)
        expected = self._require_expected()
        title: str | None = None
        try:
            raw_title = await page.title()
            title = raw_title.split(" | ", 1)[0].strip() or None
        except (PlaywrightError, TimeoutError):
            pass
        return ContentContext(
            content_id=expected.episode_id,
            work_id=expected.slug,
            episode_id=expected.episode_id,
            chapter_id=expected.episode_id,
            title=title or self._work_title,
        )

    async def go_next(self, page: Page) -> None:
        self._validate_viewer_route(page)
        if self._ended:
            return
        snapshot = await self._read_snapshot(page)
        if snapshot is None:
            raise PageChangeTimeoutError("Yanmaga reader is not ready for the next turn")
        self._validate_snapshot(snapshot)
        if snapshot.current >= snapshot.total:
            await self._wait_for_positive_terminal(
                page, timeout_ms=PAGE_CHANGE_TIMEOUT_MS
            )
            self._ended = True
            return
        self._advance_pending = True
        await page.keyboard.press("ArrowLeft")

    async def wait_for_change(
        self, page: Page, previous_identity: ContentIdentity | None
    ) -> None:
        if self._ended:
            self._validate_viewer_route(page)
            return
        if previous_identity is None or previous_identity.page_number is None:
            await self._wait_for_stable_snapshot(page, timeout_ms=PAGE_CHANGE_TIMEOUT_MS)
            self._advance_pending = False
            return
        previous = previous_identity.page_number
        deadline = monotonic() + PAGE_CHANGE_TIMEOUT_MS / 1000
        while monotonic() < deadline:
            self._validate_viewer_route(page)
            candidate = await self._read_snapshot(page)
            if candidate is not None and candidate.total != self._total_pages:
                raise UnknownPageStateError("Yanmaga reader page total changed after navigation")
            if candidate is not None and candidate.current > previous:
                stable = await self._wait_for_stable_snapshot(
                    page,
                    timeout_ms=max(1, int((deadline - monotonic()) * 1000)),
                )
                indices = self._validate_snapshot(stable)
                if stable.current <= previous or not any(
                    index not in self._captured_indices for index in indices
                ):
                    raise UnknownPageStateError("Yanmaga page turn did not reveal a new body page")
                self._advance_pending = False
                return
            await page.wait_for_timeout(RENDER_POLL_MS)
        raise PageChangeTimeoutError("Yanmaga reader did not advance within the bounded wait")

    async def collect_debug_metadata(self, page: Page) -> dict[str, object]:
        snapshot = await self._read_snapshot(page)
        visible = snapshot.visible_pages if snapshot is not None else ()
        metadata: dict[str, object] = {
            "capture_provenance": "rendered_dom_body_wrapper",
            "capture_method": "playwright_locator_screenshot_png",
            "source_native_bytes_used": False,
            "capture_viewport": f"{VIEWPORT_WIDTH}x{VIEWPORT_HEIGHT}",
            "source_segment_count": 3,
            "source_segment_widths": sorted(
                {segment.natural_width for body_page in visible for segment in body_page.segments}
            ),
        }
        if (
            snapshot is not None
            and snapshot.current == snapshot.total
            and self._captured_indices == list(range(1, snapshot.total + 1))
        ):
            terminal_page = [
                item for item in visible if item.index == snapshot.total
            ]
            metadata["terminal_proof"] = {
                "native_counter_complete": True,
                "captured_body_page_count": len(self._captured_indices),
                "body_index_sequence_complete": True,
                "terminal_wrapper_visible": len(terminal_page) == 1,
                "rental_count_one": snapshot.rental_count == 1,
                "rental_visible": snapshot.rental_visible,
                "rental_presented_in_viewport_unobstructed": snapshot.rental_presented,
                "rental_title_present": bool(snapshot.rental_title),
                "rental_title_presented_in_viewport_unobstructed": snapshot.rental_title_presented,
                "rental_next_label_match": snapshot.rental_next_label == "次の話を読む",
                "rental_next_presented_in_viewport_unobstructed": snapshot.rental_next_presented,
                "rental_next_count_one": snapshot.rental_next_count == 1,
                "rental_signup_label_match": snapshot.rental_signup_label == "無料登録して読む",
                "rental_signup_first_party_path_match": (
                    snapshot.rental_signup_same_origin
                    and snapshot.rental_signup_path == "/customers/sign-up"
                ),
                "rental_signup_forward_matches_immediate_next_row": (
                    self._signup_forward_matches_immediate_next_row(snapshot)
                ),
                "rental_signup_presented_in_viewport_unobstructed": snapshot.rental_signup_presented,
                "rental_signup_count_one": snapshot.rental_signup_count == 1,
                "menu_hidden": snapshot.menu_hidden,
                "terminal_wrapper_perimeter_owned": (
                    len(terminal_page) == 1 and terminal_page[0].perimeter_owned
                ),
                "next_arrow_count": snapshot.next_arrow_count,
                "next_arrow_hidden": snapshot.next_arrow_hidden,
                "next_arrow_parent_is_observed": snapshot.next_arrow_parent_id == "arrow-content",
                "next_arrow_parent_hidden": snapshot.next_arrow_parent_hidden,
                "requested_route_identity_matches": (
                    parse_yanmaga_viewer_url(page.url) == self._require_expected()
                ),
            }
        return metadata

    def get_output_metadata(self) -> dict[str, str | None]:
        return {
            "title": self._work_title,
            "author": None,
            "order": self._episode_title,
            "genre": None,
        }
