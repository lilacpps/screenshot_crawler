"""Free-only rendered-page capture for the observed YanmagaWeb reader."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
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
    AccessStopError,
    PageChangeTimeoutError,
    UnknownPageStateError,
    UnsupportedAccessStrategyError,
)
from screenshot_crawler.core.models import AccessStrategy, ContentContext, ContentIdentity
from screenshot_crawler.core.state import PageState
from screenshot_crawler.discovery.service import DiscoveryIncompleteError
from screenshot_crawler.site_adapters.base import (
    AccessConsumption,
    ConfirmedAccessGrant,
    SiteAdapter,
)
from screenshot_crawler.site_adapters.yanmaga.access import yanmaga_access_profile
from screenshot_crawler.site_adapters.yanmaga.discovery import (
    _SORT_OLDEST_LABEL,
    SITE_HOST,
    WAIT_ASSET_PATH,
    WAIT_BADGE_CLASS,
    WAIT_BADGE_TEXT,
    YanmagaDiscoveryAdapter,
    YanmagaEpisodeParts,
    YanmagaListingRow,
    YanmagaWorkParts,
    _parse_yanmaga_sorted_work_url,
    _validate_work_identity_urls,
    parse_yanmaga_episode_url,
    parse_yanmaga_work_url,
)
from screenshot_crawler.site_adapters.yanmaga.native_capture import (
    NativeCaptureOutcome,
    activate_yanmaga_native_observer,
    capture_yanmaga_native_webp,
    dispose_yanmaga_native_observer,
    install_yanmaga_native_observer,
    release_yanmaga_native_page,
    verify_yanmaga_native_group,
)
from screenshot_crawler.site_adapters.yanmaga.rental_history import (
    MAX_WAIT_RENTAL_COUNTDOWN_HOURS,
    RentalCountdown,
    fetch_rental_history_countdowns,
    fetch_rental_history_observations,
)
from screenshot_crawler.watchlist.models import WatchlistTarget

VIEWPORT_WIDTH = 2560
VIEWPORT_HEIGHT = 1800
PAGE_CHANGE_TIMEOUT_MS = 15_000
INITIALIZE_TIMEOUT_MS = 90_000
RENDER_POLL_MS = 100
FIRST_FREE_ACCESS_PROOF_TIMEOUT_MS = 2_000
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
_WAIT_RENTAL_MODAL_TITLE = "\u300c\u5f85\u3064\u3068\u7121\u6599....!\u300d\u3067\u30ec\u30f3\u30bf\u30eb"
_WAIT_RENTAL_PERIOD_LABEL = "\u30ec\u30f3\u30bf\u30eb\u671f\u9593"
_WAIT_RENTAL_PERIOD_VALUE = "3\u65e5\u9593"
_WAIT_RENTAL_READ_LABEL = "\u8aad\u3080"
_WAIT_END_CLOCK_SRC = (
    "https://viewer-assets.yanmaga.jp/viewer/assets/img/"
    "icon_clock-048e89030730e8f736d174dde55780bad06a38135282b236b2c20ae032812836.svg"
)
_WAIT_END_LABEL = re.compile(r"^\u3042\u3068(?:[0-9]|1[0-9]|2[0-3]):[0-5][0-9]\u3067\u7121\u6599$")
_FIRST_FREE_COMPLETION_NOTICE = "\u7121\u6599\u30ec\u30f3\u30bf\u30eb\u304c\u5b8c\u4e86\u3057\u307e\u3057\u305f"
_WAIT_TICKET_COMPLETION_NOTICE = "\u30ec\u30f3\u30bf\u30eb\u304c\u5b8c\u4e86\u3057\u307e\u3057\u305f"


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
    rental_wait_count: int = 0
    rental_wait_label: str | None = None
    rental_wait_clock_src: str | None = None
    rental_wait_presented: bool = False

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
      const waitNodes = rental ? [...rental.querySelectorAll(
        '.aspect-ratio-2-27.mt-wait > div.episode-modal-wait.content')] : [];
      const waitNode = waitNodes.length === 1 ? waitNodes[0] : null;
      const waitChildren = waitNode ? [...waitNode.children] : [];
      const waitImage = waitChildren.length === 2 &&
        waitChildren[0].tagName === 'IMG' && waitChildren[0].classList.contains('icon-clock')
        ? waitChildren[0] : null;
      const waitLabelNode = waitChildren.length === 2 && waitChildren[1].tagName === 'SPAN'
        ? waitChildren[1] : null;
      const waitPresentation = presented(waitNode);
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
      const semanticGateSelector = '[role="dialog"],[aria-modal="true"],dialog';
      const inlineRentalSelector = '.episode-modal-expire,.episode-modal-rental-detail,' +
        '.mod-modal-content-inner.episode-modal,.mod-modal-content.wrapper-mod-modal,' +
        '#js-modal-content.rental-modal,.episode-modal-point,' +
        'dl.episode-modal-point--posession,dl.episode-modal-point--necessary,' +
        '.episode-modal-short';
      const knownInlineRentalCard = node => {
        if (!rental || !rental.contains(node) || !node.matches(inlineRentalSelector) ||
            node.matches(semanticGateSelector)) return false;
        return true;
      };
      const accessGateVisible = [...document.querySelectorAll(
        '[role="dialog"],[aria-modal="true"],dialog,[class*="modal" i],[class*="alert" i]')]
        .filter(visible).some(node => /初回無料|チケット|ポイント|レンタル|購入|ログイン|会員登録|無料は1日で読める数/.test(
          (knownInlineRentalCard(node) ? '' : node.innerText || '').replace(/\s+/g,' ').trim()));
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
        rentalWaitCount:waitNodes.length,
        rentalWaitLabel:waitLabelNode ? (waitLabelNode.innerText || '').replace(/\s+/g,' ').trim() : null,
        rentalWaitClockSrc:waitImage ? (waitImage.currentSrc || waitImage.src || null) : null,
        rentalWaitPresented:!!waitNode && !!waitImage && !!waitLabelNode &&
          waitPresentation.presented && visible(waitImage) && visible(waitLabelNode),
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
        self._native_observer_installed = False
        self._last_capture_group: dict[str, object] = {}
        self._existing_access_grant_until: datetime | None = None
        self._first_free_entry_attempted = False
        self._first_free_release_state = "not_attempted"
        self._first_free_grant: ConfirmedAccessGrant | None = None
        self._first_free_completion_notice_seen = False
        self._quota_resource: str | None = None
        self._quota_entry_attempted = False
        self._quota_entry_started_at: datetime | None = None
        self._quota_release_state = "not_attempted"
        self._access_consumption = AccessConsumption()

    def configure_existing_access_grant(
        self, access_granted_until: datetime | None
    ) -> None:
        if (
            isinstance(access_granted_until, datetime)
            and access_granted_until.tzinfo is not None
            and access_granted_until.utcoffset() is not None
        ):
            self._existing_access_grant_until = access_granted_until
        else:
            self._existing_access_grant_until = None

    async def prepare_page(self, page: Page) -> None:
        try:
            await install_yanmaga_native_observer(page)
        except PlaywrightError:
            self._native_observer_installed = False
            return
        self._native_observer_installed = True

    async def prepare_entry_only_page(self, page: Page) -> None:
        del page
        self._native_observer_installed = False

    def get_access_profile(self) -> AccessProfile:
        return yanmaga_access_profile()

    def get_initialize_timeout_ms(self, default_ms: int) -> int:
        del default_ms
        return INITIALIZE_TIMEOUT_MS

    async def _dispose_native_observer(self, page: Page) -> None:
        await dispose_yanmaga_native_observer(page)
        self._native_observer_installed = False

    async def configure_run(self, page: Page, access_strategy: AccessStrategy) -> None:
        del page
        if access_strategy not in {"auto", "direct", "quota"}:
            raise UnsupportedAccessStrategyError(
                "Yanmaga supports access_strategy='auto', 'direct', or 'quota'"
            )
        self._access_strategy = access_strategy

    async def configure_quota_resource(
        self, page: Page, quota_resource: str | None
    ) -> None:
        del page
        if self._access_strategy == "quota":
            if quota_resource != "work_ticket":
                raise UnsupportedAccessStrategyError(
                    "Yanmaga quota access requires quota_resource='work_ticket'"
                )
            if self._expected is None or self._expected_external_id is None:
                raise UnknownPageStateError(
                    "Yanmaga work_ticket requires a configured Catalog target identity"
                )
            self._quota_resource = quota_resource
            self._quota_entry_attempted = False
            self._quota_entry_started_at = None
            self._quota_release_state = "not_attempted"
            self._access_consumption = AccessConsumption()
        elif quota_resource is not None:
            raise UnsupportedAccessStrategyError(
                "Yanmaga work_ticket requires access_strategy='quota'"
            )

    async def configure_target_identity(self, external_id: str, work_key: str) -> None:
        parsed = parse_yanmaga_composite_id(external_id)
        if parsed is None:
            raise UnknownPageStateError("Yanmaga Catalog identity is malformed")
        slug, episode_id = parsed
        self._expected = YanmagaEpisodeParts(slug, episode_id)
        self._expected_external_id = external_id
        self._work_key = work_key
        self._first_free_entry_attempted = False
        self._first_free_release_state = "not_attempted"
        self._first_free_grant = None
        self._first_free_completion_notice_seen = False
        self._quota_resource = None
        self._quota_entry_attempted = False
        self._quota_entry_started_at = None
        self._quota_release_state = "not_attempted"
        self._access_consumption = AccessConsumption()
        self._existing_access_grant_until = None
        self._listing_rows = None
        self._viewer_url = None

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
        try:
            await self._initialize_impl(page, entry_only=False)
        except BaseException:
            await self._dispose_native_observer(page)
            raise

    async def initialize_entry_only(self, page: Page) -> None:
        if self._access_strategy != "quota" or self._quota_resource != "work_ticket":
            raise UnsupportedAccessStrategyError(
                "Yanmaga entry-only execution requires quota/work_ticket"
            )
        try:
            await self._initialize_impl(page, entry_only=True)
        except BaseException:
            await self._dispose_native_observer(page)
            raise

    def get_access_consumption(self) -> AccessConsumption:
        return self._access_consumption

    async def _initialize_impl(self, page: Page, *, entry_only: bool) -> None:
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
        if listing is None or not (listing.anonymous or listing.authenticated):
            raise UnknownPageStateError(
                "Yanmaga current listing lacks explicit login-state proof"
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
        if match.source.url != self._source_url:
            raise UnknownPageStateError("Yanmaga listing route differs from the requested source URL")
        classified_free = match.source.access_mode == "free"
        quota_candidate = (
            match.source.access_mode == "quota"
            and row.wait_free_marker
            and listing.authenticated
            and not row.free_marker
            and not row.first_free_marker
        )
        quota_attempt = self._access_strategy == "quota"
        if quota_attempt and (
            self._quota_resource != "work_ticket" or not quota_candidate
        ):
            raise AccessResourceUnavailableError(
                "yanmaga_work_ticket_requires_exact_authenticated_wait_target"
            )
        if entry_only and not quota_attempt:
            raise UnsupportedAccessStrategyError(
                "Yanmaga entry-only execution requires a current wait/work_ticket candidate"
            )
        authenticated_first_free = (
            row.first_free_marker and listing.authenticated and classified_free
        )
        trusted_until = self._active_existing_grant_until()
        fresh_existing_grant: RentalCountdown | None = None
        if trusted_until is not None and not row.free_marker:
            if not listing.authenticated or listing.mypage_href is None:
                raise AccessResourceUnavailableError("yanmaga_existing_grant_auth_unknown")
            proofs = await fetch_rental_history_countdowns(
                page,
                observed_mypage_href=listing.mypage_href,
                targets=(expected,),
                max_countdown_hours=MAX_WAIT_RENTAL_COUNTDOWN_HOURS,
            )
            fresh_existing_grant = next(
                (
                    countdown
                    for external_id, countdown in proofs
                    if external_id == self._expected_external_id and countdown.active
                ),
                None,
            )
            if fresh_existing_grant is None:
                raise AccessResourceUnavailableError("yanmaga_existing_grant_not_active")

        fresh_first_free = (
            authenticated_first_free and self._existing_access_grant_until is None
        )
        if quota_attempt:
            if fresh_existing_grant is not None:
                raise AccessResourceUnavailableError(
                    "yanmaga_wait_target_already_has_untrusted_active_history"
                )
            if listing.mypage_href is None:
                raise UnknownPageStateError(
                    "Yanmaga wait target has no observed account link"
                )
            history = await fetch_rental_history_observations(
                page,
                observed_mypage_href=listing.mypage_href,
                targets=(expected,),
                max_countdown_hours=MAX_WAIT_RENTAL_COUNTDOWN_HOURS,
            )
            observation = next(
                (
                    value
                    for value in history or ()
                    if value.external_id == self._expected_external_id
                ),
                None,
            )
            if history is None or observation is None:
                raise UnknownPageStateError(
                    "Yanmaga wait target history status is unknown"
                )
            if observation.countdown is not None and observation.countdown.active:
                raise AccessResourceUnavailableError(
                    "yanmaga_wait_target_has_active_history_without_trusted_grant"
                )
        elif row.free_marker and classified_free:
            pass
        elif fresh_first_free:
            if listing.mypage_href is None:
                raise UnknownPageStateError("Yanmaga first-free target has no observed account link")
            if getattr(self, "_confirmed_access_grant_observer", None) is None:
                raise AccessResourceUnavailableError(
                    "yanmaga_first_free_requires_batch_grant_observer"
                )
        elif fresh_existing_grant is not None:
            pass
        elif row.known_restricted and not row.red_marker_present:
            raise AccessResourceUnavailableError(
                "yanmaga_target_not_currently_free_or_granted"
            )
        else:
            raise UnknownPageStateError(
                "Yanmaga target lacks an exact current public-free, first-free, or trusted-grant proof"
            )
        self._work_title = match.item.canonical_title or expected.slug
        self._episode_title = match.item.order_label
        if not self._episode_title:
            raise UnknownPageStateError("Yanmaga target episode label is unavailable")

        if row.first_free_marker and not fresh_first_free and fresh_existing_grant is None:
            raise AccessResourceUnavailableError("yanmaga_first_free_provenance_is_unknown")
        await self._validate_pre_entry_target(
            page,
            expected,
            row,
            listing,
            trusted_grant=fresh_existing_grant is not None,
            classified_access_mode=match.source.access_mode,
            wait_quota=row.wait_free_marker,
            require_charged=quota_attempt,
        )
        if fresh_first_free and self._first_free_entry_attempted:
            raise AccessResourceUnavailableError("yanmaga_first_free_entry_already_attempted")
        self._first_free_entry_attempted = bool(fresh_first_free)
        if fresh_first_free:
            self._first_free_release_state = "attempted_unknown"
        if quota_attempt and self._quota_entry_attempted:
            raise AccessResourceUnavailableError(
                "yanmaga_work_ticket_entry_already_attempted"
            )
        if fresh_existing_grant is not None:
            self._require_live_existing_grant(fresh_existing_grant)
        try:
            await page.goto(self._source_url, wait_until="domcontentloaded", timeout=30_000)
        except (PlaywrightError, TimeoutError) as entry_error:
            if fresh_first_free:
                try:
                    await self._confirm_and_persist_first_free_grant(
                        page, expected, listing.mypage_href or ""
                    )
                except AccessStopError:
                    raise
                except Exception as confirmation_error:  # noqa: BLE001
                    entry_error.add_note(
                        "Yanmaga first-free post-navigation confirmation remained unknown: "
                        f"{type(confirmation_error).__name__}"
                    )
            raise
        if quota_attempt:
            try:
                await self._submit_wait_rental_modal(page, expected)
            except AccessStopError:
                raise
            except (PlaywrightError, TimeoutError, AccessResourceUnavailableError) as entry_error:
                if not self._quota_entry_attempted:
                    raise
                try:
                    await self._confirm_and_record_quota_consumption(
                        page, expected, listing.mypage_href or ""
                    )
                except AccessStopError:
                    raise
                except Exception as confirmation_error:  # noqa: BLE001
                    entry_error.add_note(
                        "Yanmaga work-ticket post-submit confirmation remained unknown: "
                        f"{type(confirmation_error).__name__}"
                    )
                raise
            if not await self._confirm_and_record_quota_consumption(
                page, expected, listing.mypage_href or ""
            ):
                raise AccessResourceUnavailableError(
                    "yanmaga_work_ticket_consumption_unconfirmed_no_retry"
                )
            if self._access_consumption.access_granted_until is None:
                raise UnknownPageStateError(
                    "yanmaga_work_ticket_confirmed_grant_expiry_unavailable"
                )
        else:
            self._validate_viewer_route(page)
        if fresh_first_free and not await self._confirm_and_persist_first_free_grant(
                page, expected, listing.mypage_href or ""
        ):
            raise AccessResourceUnavailableError(
                "yanmaga_first_free_access_or_finite_grant_unconfirmed"
            )
        if entry_only:
            self._viewer_url = page.url
            return
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

    def _active_existing_grant_until(self) -> datetime | None:
        value = self._existing_access_grant_until
        if (
            value is None
            or value.tzinfo is None
            or value.utcoffset() is None
            or value.astimezone(UTC) <= datetime.now(UTC)
        ):
            return None
        return value

    @property
    def first_free_release_state(self) -> str:
        """Return a non-sensitive state for this run's one permitted entry."""

        return self._first_free_release_state

    @property
    def quota_release_state(self) -> str:
        """Return whether this run's one ticket entry was confirmed."""

        return self._quota_release_state

    def _require_live_existing_grant(self, countdown: RentalCountdown) -> None:
        trusted_until = self._active_existing_grant_until()
        now = datetime.now(UTC)
        if (
            trusted_until is None
            or not countdown.active
            or countdown.observed_at.tzinfo is None
            or countdown.observed_at.utcoffset() is None
            or countdown.observed_at.astimezone(UTC) > now
        ):
            raise AccessResourceUnavailableError(
                "yanmaga_existing_grant_not_active_before_entry"
            )

    async def _confirm_and_persist_first_free_grant(
        self,
        page: Page,
        expected: YanmagaEpisodeParts,
        observed_mypage_href: str,
    ) -> bool:
        if self._first_free_grant is not None:
            return self._first_free_release_state == "persisted"
        if not self._first_free_entry_attempted:
            raise AccessResourceUnavailableError(
                "yanmaga_first_free_confirmation_without_entry_attempt"
            )
        if not await self._has_first_free_access_proof(page, expected):
            return False

        proofs = await fetch_rental_history_countdowns(
            page,
            observed_mypage_href=observed_mypage_href,
            targets=(expected,),
        )
        if not await self._has_first_free_access_proof(page, expected):
            return False
        external_id = self._expected_external_id
        countdown = next(
            (
                value
                for proof_external_id, value in proofs
                if proof_external_id == external_id and value.active
            ),
            None,
        )
        now = datetime.now(UTC)
        if (
            countdown is None
            or countdown.access_granted_until is None
            or countdown.access_granted_until.tzinfo is None
            or countdown.access_granted_until.utcoffset() is None
            or countdown.access_granted_until.astimezone(UTC) <= now
            or countdown.expiry_evidence != "site_countdown_lower_bound"
            or countdown.observed_at.tzinfo is None
            or countdown.observed_at.utcoffset() is None
            or countdown.observed_at.astimezone(UTC) > now
        ):
            return False

        grant = ConfirmedAccessGrant(
            site="yanmaga",
            external_id=external_id or "",
            observed_at=countdown.observed_at,
            access_granted_until=countdown.access_granted_until,
            expiry_evidence=countdown.expiry_evidence,  # type: ignore[arg-type]
        )
        self._first_free_grant = grant
        self._first_free_release_state = "site_confirmed"
        self.report_confirmed_access_grant(grant)
        self._first_free_release_state = "persisted"
        return True

    async def _confirm_and_record_quota_consumption(
        self,
        page: Page,
        expected: YanmagaEpisodeParts,
        observed_mypage_href: str,
    ) -> bool:
        if self._access_consumption.consumed:
            return self._quota_release_state == "site_confirmed"
        started_at = self._quota_entry_started_at
        if (
            not self._quota_entry_attempted
            or started_at is None
            or self._expected_external_id is None
        ):
            raise AccessResourceUnavailableError(
                "yanmaga_work_ticket_confirmation_without_entry_attempt"
            )
        self._validate_viewer_route(page)
        if not await self._has_first_free_access_proof(
            page, expected, completion_notice=_WAIT_TICKET_COMPLETION_NOTICE
        ):
            return False
        observations = await fetch_rental_history_observations(
            page,
            observed_mypage_href=observed_mypage_href,
            targets=(expected,),
            max_countdown_hours=MAX_WAIT_RENTAL_COUNTDOWN_HOURS,
        )
        observation = next(
            (
                value
                for value in observations or ()
                if value.external_id == self._expected_external_id
            ),
            None,
        )
        countdown = observation.countdown if observation is not None else None
        observed_at = countdown.observed_at if countdown is not None else None
        now = datetime.now(UTC)
        if (
            countdown is None
            or not countdown.active
            or observed_at is None
            or observed_at.tzinfo is None
            or observed_at.utcoffset() is None
            or observed_at.astimezone(UTC) < started_at.astimezone(UTC)
            or observed_at.astimezone(UTC) > now
        ):
            return False
        self._validate_viewer_route(page)
        if not await self._has_first_free_access_proof(
            page, expected, completion_notice=_WAIT_TICKET_COMPLETION_NOTICE
        ):
            return False
        access_granted_until = countdown.access_granted_until
        if (
            countdown.expiry_evidence
            not in {"site_countdown_lower_bound", "site_day_countdown_lower_bound"}
            or access_granted_until is None
            or access_granted_until.tzinfo is None
            or access_granted_until.utcoffset() is None
            or access_granted_until.astimezone(UTC) <= now
        ):
            access_granted_until = None
        self._access_consumption = AccessConsumption(
            consumed=True,
            resource="work_ticket",
            consumed_at=observed_at,
            access_granted_until=access_granted_until,
        )
        self._quota_release_state = "site_confirmed"
        return True

    async def _validate_pre_entry_target(
        self,
        page: Page,
        expected: YanmagaEpisodeParts,
        row: YanmagaListingRow,
        listing,
        *,
        trusted_grant: bool,
        classified_access_mode: str,
        wait_quota: bool,
        require_charged: bool,
    ) -> None:
        expected_public_path = (
            f"/comics/{quote(expected.slug, safe='')}/{expected.episode_id}"
        )
        expected_work_path = f"/comics/{quote(expected.slug, safe='')}"
        state = await page.evaluate(
            r"""(args) => {
              const visible = element => {
                if (!element || element.getClientRects().length === 0) return false;
                for (let node = element; node; node = node.parentElement) {
                  const style = getComputedStyle(node);
                  if (node.hidden || style.display === 'none' || style.visibility === 'hidden' ||
                      style.visibility === 'collapse' || Number(style.opacity) === 0) return false;
                }
                const box = element.getBoundingClientRect();
                return box.width > 0 && box.height > 0;
              };
              const current = new URL(location.href);
              const canonical = [...document.querySelectorAll('link[rel="canonical"]')];
              const og = [...document.querySelectorAll('meta[property="og:url"]')];
              const sortControls = [...document.querySelectorAll('a.ga-sort.nav-link')].map((element, index) => ({
                index,
                tag: element.tagName,
                visible: visible(element),
                text: (element.innerText || '').replace(/\s+/g, ' ').trim(),
                classes: [...element.classList],
                href: element.href,
                ariaCurrent: element.getAttribute('aria-current'),
                ariaPressed: element.getAttribute('aria-pressed'),
                ariaSelected: element.getAttribute('aria-selected')
              }));
              const rows = [...document.querySelectorAll('.detailv2-episodes .mod-episode-item')];
              const matched = rows.filter(row => [...row.querySelectorAll('a[href]')].some(anchor => {
                try { return new URL(anchor.href).pathname === args.episodePath; }
                catch { return false; }
              }));
              const row = matched.length === 1 ? matched[0] : null;
              const anchors = row ? [...row.querySelectorAll('a[href]')].filter(anchor => {
                try { return new URL(anchor.href).pathname === args.episodePath; }
                catch { return false; }
              }) : [];
              const exactAnchors = anchors.filter(anchor => {
                try {
                  const href = new URL(anchor.href);
                  const expected = new URL(args.sourceUrl);
                  return href.href === expected.href && href.protocol === 'https:' &&
                    href.origin === 'https://yanmaga.jp' && !href.username && !href.password &&
                    !href.search && !href.hash;
                } catch { return false; }
              });
              const markers = row ? [...row.querySelectorAll('.mod-episode-point--free')] : [];
              const first = markers.filter(marker => marker.classList.contains('by_first_time'));
              const waitBadges = row ? [...row.querySelectorAll('span.mod-episode-free_browse')] : [];
              const waitBadge = waitBadges.length === 1 ? waitBadges[0] : null;
              const waitImages = waitBadge ? [...waitBadge.querySelectorAll('img')] : [];
              const waitImage = waitImages.length === 1 ? waitImages[0] : null;
              let originalURL = null;
              try {
                const original = row?.getAttribute('data-original-url');
                originalURL = original ? new URL(original, location.href).href : null;
              } catch (_) {}
              const waitBadgeOkay = waitBadges.length === 1 && visible(waitBadge) &&
                waitBadge.className === args.waitBadgeClass &&
                (waitBadge.innerText || '').trim() === args.waitBadgeText &&
                waitImages.length === 1 && visible(waitImage) &&
                waitImage.src === args.waitAssetUrl &&
                row?.getAttribute('data-is-free') === 'true' &&
                originalURL === args.sourceUrl && anchors.length === 1 &&
                exactAnchors.length === 1 && !first.length && !markers.length;
              const chargedCards = [...document.querySelectorAll(
                '.episode-ui .episode-free-time.charged')];
              const chargedCard = chargedCards.length === 1 ? chargedCards[0] : null;
              const chargeLabels = chargedCard
                ? [...chargedCard.querySelectorAll('.episode-free-time-bar-label')] : [];
              const chargeImages = chargedCard
                ? [...chargedCard.querySelectorAll('.episode-free-time-label img')] : [];
              const chargedProof = chargedCards.length === 1 && chargedCard.tagName === 'DIV' &&
                visible(chargedCard) && chargeLabels.length === 1 && visible(chargeLabels[0]) &&
                (chargeLabels[0].innerText || '').replace(/\s+/g, ' ').trim() === args.chargedLabel &&
                chargeImages.length === 1 && visible(chargeImages[0]) &&
                chargeImages[0].src === args.waitAssetUrl;
              const inactive = element => {
                const ariaDisabled = element.getAttribute('aria-disabled');
                return element.hasAttribute('disabled') || element.hasAttribute('inert') ||
                  (ariaDisabled !== null && ariaDisabled !== 'false');
              };
              const firstExact = first.length === 1 && visible(first[0]) &&
                first[0].innerText.trim() === args.firstLabel &&
                first[0].className === 'mod-episode-point--free by_first_time';
              const redExact = markers.length === 1 && visible(markers[0]) &&
                markers[0].innerText.trim() === args.freeLabel &&
                markers[0].className === 'mod-episode-point--free' &&
                getComputedStyle(markers[0]).color === args.freeColor;
              const otherFreeBadge = row && [...row.querySelectorAll(
                '.mod-episode-point,[class*="mod-episode-point--"]')].some(marker =>
                  !markers.includes(marker) &&
                  marker.innerText.replace(/\s+/g,' ').trim() === args.freeLabel);
              const myPages = [...document.querySelectorAll('a[href]')].filter(anchor => {
                try {
                  const url = new URL(anchor.href);
                  return visible(anchor) && url.origin === location.origin &&
                    url.pathname === '/mypage' && !url.search && !url.hash &&
                    !url.username && !url.password;
                } catch { return false; }
              });
              const signIns = [...document.querySelectorAll('a[href]')].filter(anchor => {
                try {
                  const url = new URL(anchor.href);
                  return visible(anchor) && url.origin === location.origin &&
                    url.pathname === '/customers/sign-up' &&
                    /\u30ed\u30b0\u30a4\u30f3|\u4f1a\u54e1\u767b\u9332|\u65b0\u898f\u767b\u9332/.test(anchor.innerText || '');
                } catch { return false; }
              });
              const signOuts = [...document.querySelectorAll('a[href],button')].filter(element => {
                const path = element instanceof HTMLAnchorElement ? new URL(element.href).pathname : '';
                return visible(element) && /(?:sign.?out|log.?out)/i.test(path + ' ' + element.className);
              });
              const pageOkay = current.protocol === 'https:' && current.hostname === 'yanmaga.jp' &&
                !current.username && !current.password && current.pathname === args.workPath &&
                !current.hash && (current.search === '' || current.search === '?sort=older');
              const loginOkay = args.authenticated
                ? myPages.length > 0 && signIns.length === 0 && signOuts.length === 0
                : myPages.length === 0 && signIns.length > 0 && signOuts.length === 0;
              const modeOkay = args.waitQuota
                ? waitBadgeOkay
                : args.firstFree
                ? markers.length === 1 && firstExact && !redExact
                : args.trustedGrant
                  ? markers.length === 0 && row.querySelector('.by_wait,.js-modal') === null
                  : redExact && first.length === 0;
              return {
                documentUrl: current.href,
                canonicalCount: canonical.length,
                canonicalUrl: canonical.length === 1 ? canonical[0].href : null,
                ogCount: og.length,
                ogUrl: og.length === 1 ? og[0].content : null,
                sortControls,
                pageOkay,
                loginOkay,
                rowCount: matched.length,
                anchorCount: anchors.length,
                exactAnchorCount: exactAnchors.length,
                targetVisible: row !== null && visible(row) && anchors.length === 1 &&
                  exactAnchors.length === 1 && visible(anchors[0]),
                targetInactive: row === null || inactive(row) || anchors.some(inactive),
                modeOkay,
                waitBadgeOkay,
                chargedProof,
                noWaitModal: row !== null && !row.matches('.by_wait,.js-modal') &&
                  row.querySelector('.by_wait,.js-modal') === null,
                noOtherFreeBadge: !otherFreeBadge,
                noRowButtons: row !== null && row.querySelectorAll(
                  'button,[role="button"],input[type="button"],input[type="submit"]').length === 0,
                noInlineHandler: row !== null && ![row, ...row.querySelectorAll('*')].some(element =>
                  [...element.attributes].some(attribute => /^on/i.test(attribute.name)))
              };
            }""",
            {
                "episodePath": expected_public_path,
                "workPath": expected_work_path,
                "workUrl": self._work_url,
                "sourceUrl": self._source_url,
                "authenticated": listing.authenticated,
                "firstFree": row.first_free_marker and classified_access_mode == "free",
                "trustedGrant": trusted_grant,
                "waitQuota": wait_quota,
                "waitBadgeClass": WAIT_BADGE_CLASS,
                "waitBadgeText": WAIT_BADGE_TEXT,
                "waitAssetUrl": f"https://{SITE_HOST}{WAIT_ASSET_PATH}",
                "chargedLabel": "\u30c1\u30e3\u30fc\u30b8\u5b8c\u4e86",
                "firstLabel": "\u521d\u56de\u7121\u6599",
                "freeLabel": "\u7121\u6599",
                "freeColor": "rgb(220, 0, 0)",
            },
        )
        identity_ok = False
        if isinstance(state, dict):
            try:
                document_url = state.get("documentUrl")
                canonical_url = state.get("canonicalUrl")
                og_url = state.get("ogUrl")
                sort_controls = state.get("sortControls")
                work = YanmagaWorkParts(expected.slug)
                if (
                    state.get("canonicalCount") != 1
                    or state.get("ogCount") != 1
                    or not isinstance(sort_controls, list)
                    or not isinstance(document_url, str)
                    or page.url != document_url
                ):
                    raise DiscoveryIncompleteError("Yanmaga work identity changed before entry")
                sorted_document = _parse_yanmaga_sorted_work_url(document_url, work)
                if sort_controls:
                    YanmagaDiscoveryAdapter._validate_sort_controls(
                        sort_controls,
                        work,
                        expected_active_label=_SORT_OLDEST_LABEL,
                    )
                elif sorted_document:
                    raise DiscoveryIncompleteError(
                        "Yanmaga sorted work document lacks oldest-first UI proof"
                    )
                elif parse_yanmaga_work_url(document_url) != work:
                    raise DiscoveryIncompleteError("Yanmaga base work identity changed")
                _validate_work_identity_urls(
                    document_url,
                    canonical_url,
                    og_url,
                    work,
                    allow_sorted_identity=sorted_document,
                )
                identity_ok = True
            except DiscoveryIncompleteError:
                identity_ok = False
        if (
            not isinstance(state, dict)
            or state.get("pageOkay") is not True
            or not identity_ok
            or state.get("loginOkay") is not True
            or state.get("rowCount") != 1
            or state.get("anchorCount") != 1
            or state.get("exactAnchorCount") != 1
            or state.get("targetVisible") is not True
            or state.get("targetInactive") is not False
            or state.get("modeOkay") is not True
            or (wait_quota and state.get("waitBadgeOkay") is not True)
            or (require_charged and state.get("chargedProof") is not True)
            or state.get("noWaitModal") is not True
            or state.get("noOtherFreeBadge") is not True
            or state.get("noRowButtons") is not True
            or state.get("noInlineHandler") is not True
            or row.url != self._source_url
            or (row.first_free_marker and not listing.authenticated)
        ):
            raise UnknownPageStateError(
                "Yanmaga target row, login state, or access marker changed before entry"
            )

    async def _validate_wait_rental_modal(
        self,
        page: Page,
        expected: YanmagaEpisodeParts,
    ) -> Locator:
        """Bind the observed wait-rental POST form to this exact episode."""

        expected_action_path = (
            f"/rental/episodes/{expected.episode_id}/by_free_waits"
        )
        state = await page.evaluate(
            r"""(args) => {
              const visible = element => {
                if (!element || element.getClientRects().length === 0) return false;
                for (let node = element; node; node = node.parentElement) {
                  const style = getComputedStyle(node);
                  if (node.hidden || style.display === 'none' || style.visibility === 'hidden' ||
                      style.visibility === 'collapse' || Number(style.opacity) === 0) return false;
                }
                const rect = element.getBoundingClientRect();
                return rect.width > 0 && rect.height > 0;
              };
              const normalize = value => (value || '').normalize('NFKC').replace(/\s+/gu, ' ').trim();
              const current = new URL(location.href);
              const canonical = [...document.querySelectorAll('link[rel="canonical"]')];
              const og = [...document.querySelectorAll('meta[property="og:url"]')];
              const visibleOuter = [...document.querySelectorAll(
                'div.mod-modal-content.js-modal-content')].filter(visible);
              const active = [...document.querySelectorAll(
                'div.mod-modal-content-inner.episode-modal.active')].filter(visible);
              const modal = active.length === 1 ? active[0] : null;
              const outer = modal ? modal.closest('div.mod-modal-content.js-modal-content') : null;
              const titles = modal ? [...modal.querySelectorAll('p.mod-modal-title')]
                .filter(visible) : [];
              const workTitles = modal ? [...modal.querySelectorAll('p.episode-modal-title')]
                .filter(visible) : [];
              const episodeTitles = modal ? [...modal.querySelectorAll('p.episode-modal-eptitle')]
                .filter(visible) : [];
              const details = modal ? [...modal.querySelectorAll('div.episode-modal-rental-detail')] : [];
              const detail = details.length === 1 ? details[0] : null;
              const periods = detail ? [...detail.querySelectorAll('div.episode-modal-expire')] : [];
              const period = periods.length === 1 ? periods[0] : null;
              const values = period ? [...period.querySelectorAll('span')].filter(visible) : [];
              const forms = modal ? [...modal.querySelectorAll('form.button_to')] : [];
              const form = forms.length === 1 ? forms[0] : null;
              const buttons = form ? [...form.querySelectorAll(
                'button#free-browse-rental.mod-button--orange[type="submit"]')].filter(visible) : [];
              const button = buttons.length === 1 ? buttons[0] : null;
              const elements = form ? [...form.elements] : [];
              const submitterOverrides = ['formaction', 'formmethod', 'formtarget',
                'formenctype', 'formnovalidate', 'form'];
              const submitterOverridesAbsent = button !== null &&
                submitterOverrides.every(name => !button.hasAttribute(name));
              const authFields = elements.filter(element => element.tagName === 'INPUT' &&
                element.type === 'hidden' && element.name === 'authenticity_token');
              const otherFields = elements.filter(element => element !== button &&
                !authFields.includes(element));
              let actionOkay = false;
              try {
                const actionAttribute = form?.getAttribute('action');
                const action = new URL(actionAttribute || '', location.href);
                actionOkay = actionAttribute === args.actionPath &&
                  action.protocol === 'https:' && action.origin === 'https://yanmaga.jp' &&
                  !action.username && !action.password && action.pathname === args.actionPath &&
                  !action.search && !action.hash;
              } catch (_) {}
              const sourceOkay = current.protocol === 'https:' &&
                current.origin === 'https://yanmaga.jp' && !current.username && !current.password &&
                current.href === args.sourceUrl && !current.search && !current.hash;
              const canonicalOkay = canonical.length === 1 && canonical[0].href === args.workUrl;
              const ogOkay = og.length === 1 && og[0].content === args.sourceUrl;
              const titleOkay = titles.length === 1 && normalize(titles[0].textContent) === args.modalTitle;
              const workOkay = workTitles.length === 1 &&
                normalize(workTitles[0].textContent) === normalize(args.workTitle);
              const episodeOkay = episodeTitles.length === 1 &&
                normalize(episodeTitles[0].textContent) === normalize(args.episodeTitle);
              const periodOkay = details.length === 1 && detail && period &&
                period.parentElement === detail && normalize(period.textContent) ===
                  args.periodLabel + ' / ' + args.periodValue && values.length === 1 &&
                normalize(values[0].textContent) === args.periodValue;
              const chargedCards = [...document.querySelectorAll(
                '.episode-ui .episode-free-time.charged')].filter(visible);
              const charged = chargedCards.length === 1 ? chargedCards[0] : null;
              const chargedLabels = charged
                ? [...charged.querySelectorAll('.episode-free-time-bar-label')].filter(visible) : [];
              const chargedImages = charged
                ? [...charged.querySelectorAll('.episode-free-time-label img')].filter(visible) : [];
              const chargedOkay = chargedCards.length === 1 && charged.tagName === 'DIV' &&
                chargedLabels.length === 1 && normalize(chargedLabels[0].textContent) ===
                  args.chargedLabel && chargedImages.length === 1 &&
                chargedImages[0].src === args.waitAssetUrl;
              const myPages = [...document.querySelectorAll('a[href]')].filter(anchor => {
                try {
                  const url = new URL(anchor.href);
                  return visible(anchor) && url.protocol === 'https:' &&
                    url.origin === 'https://yanmaga.jp' && url.pathname === '/mypage' &&
                    !url.username && !url.password && !url.search && !url.hash;
                } catch (_) { return false; }
              });
              const signIns = [...document.querySelectorAll('a[href]')].filter(anchor => {
                try {
                  const url = new URL(anchor.href);
                  return visible(anchor) && url.origin === 'https://yanmaga.jp' &&
                    ['/customers/sign-in', '/customers/sign-up'].includes(url.pathname) &&
                    /ログイン|会員登録|新規登録/.test(anchor.innerText || '');
                } catch (_) { return false; }
              });
              const signOuts = [...document.querySelectorAll('a[href],button')].filter(element => {
                const path = element instanceof HTMLAnchorElement ? element.pathname : '';
                return visible(element) && /(?:sign.?out|log.?out)/i.test(
                  path + ' ' + element.className);
              });
              const authOkay = myPages.length > 0 && signIns.length === 0 && signOuts.length === 0;
              const formOkay = forms.length === 1 && form && form.method.toLowerCase() === 'post' &&
                form.getAttribute('method') === 'post' && form.dataset.remote === 'true' &&
                !form.hasAttribute('target') && actionOkay &&
                elements.length === 2 && authFields.length === 1 && otherFields.length === 0 &&
                buttons.length === 1 && button.form === form &&
                button.closest('form') === form && submitterOverridesAbsent &&
                !button.disabled &&
                normalize(button.innerText) === args.readLabel;
              return {
                sourceOkay,
                canonicalOkay,
                ogOkay,
                authOkay,
                chargedOkay,
                visibleOuterCount: visibleOuter.length,
                activeCount: active.length,
                outerBound: outer !== null && visible(outer) && visibleOuter.includes(outer),
                titleOkay,
                workOkay,
                episodeOkay,
                periodOkay,
                formOkay,
                buttonVisible: button !== null && visible(button),
                buttonEnabled: button !== null && !button.disabled &&
                  button.getAttribute('aria-disabled') !== 'true',
                submitterOverridesAbsent
              };
            }""",
            {
                "sourceUrl": self._source_url,
                "workUrl": self._work_url,
                "actionPath": expected_action_path,
                "modalTitle": _WAIT_RENTAL_MODAL_TITLE,
                "workTitle": self._work_title,
                "episodeTitle": self._episode_title,
                "periodLabel": _WAIT_RENTAL_PERIOD_LABEL,
                "periodValue": _WAIT_RENTAL_PERIOD_VALUE,
                "readLabel": _WAIT_RENTAL_READ_LABEL,
                "chargedLabel": "\u30c1\u30e3\u30fc\u30b8\u5b8c\u4e86",
                "waitAssetUrl": f"https://{SITE_HOST}{WAIT_ASSET_PATH}",
            },
        )
        if not isinstance(state, dict) or any(
            state.get(key) is not True
            for key in (
                "sourceOkay",
                "canonicalOkay",
                "ogOkay",
                "authOkay",
                "chargedOkay",
                "outerBound",
                "titleOkay",
                "workOkay",
                "episodeOkay",
                "periodOkay",
                "formOkay",
                "buttonVisible",
                "buttonEnabled",
                "submitterOverridesAbsent",
            )
        ) or state.get("visibleOuterCount") != 1 or state.get("activeCount") != 1:
            raise UnknownPageStateError(
                "Yanmaga wait-rental modal did not match the exact observed episode form"
            )

        expected_action = (
            f"/rental/episodes/{expected.episode_id}/by_free_waits"
        )
        return page.locator(
            "div.mod-modal-content.js-modal-content "
            "div.mod-modal-content-inner.episode-modal.active "
            f'form.button_to[method="post"][data-remote="true"][action="{expected_action}"]:not([target]) '
            '> button#free-browse-rental.mod-button--orange[type="submit"]'
            ':not([formaction]):not([formmethod]):not([formtarget]):not([formenctype])'
            ':not([formnovalidate]):not([form])'
        )

    async def _submit_wait_rental_modal(
        self,
        page: Page,
        expected: YanmagaEpisodeParts,
    ) -> None:
        # The Source document's DOMContentLoaded can precede the site's
        # client-rendered rental modal. Wait for the observed active modal and
        # its visible button before taking the strict, final DOM snapshot.
        await page.locator(
            "div.mod-modal-content.js-modal-content "
            "div.mod-modal-content-inner.episode-modal.active #free-browse-rental"
        ).wait_for(state="visible", timeout=PAGE_CHANGE_TIMEOUT_MS)

        action_url = (
            f"https://{SITE_HOST}/rental/episodes/{expected.episode_id}/by_free_waits"
        )
        action_path = urlsplit(action_url).path

        def expected_response(response) -> bool:
            request = response.request
            parsed = urlsplit(response.url)
            return (
                request.method.upper() == "POST"
                and parsed.scheme == "https"
                and parsed.netloc == SITE_HOST
                and parsed.path == action_path
                and not parsed.query
                and not parsed.fragment
                and response.url == action_url
            )

        async with page.expect_response(
            expected_response,
            timeout=PAGE_CHANGE_TIMEOUT_MS,
        ) as response_info:
            button = await self._validate_wait_rental_modal(page, expected)
            # Source GET only displayed the rental form. Mark the one possible
            # ticket action immediately before the observed UI click.
            self._quota_entry_attempted = True
            self._quota_entry_started_at = datetime.now(UTC)
            self._quota_release_state = "attempted_unknown"
            await button.click(timeout=PAGE_CHANGE_TIMEOUT_MS, no_wait_after=True)
        response = await response_info.value
        if response.status >= 400:
            raise AccessResourceUnavailableError(
                "yanmaga_wait_rental_submit_response_not_successful"
            )
        await page.wait_for_url(
            lambda value: parse_yanmaga_viewer_url(str(value)) == expected,
            timeout=PAGE_CHANGE_TIMEOUT_MS,
            wait_until="domcontentloaded",
        )

    async def _has_first_free_access_proof(
        self,
        page: Page,
        expected: YanmagaEpisodeParts,
        *,
        completion_notice: str = _FIRST_FREE_COMPLETION_NOTICE,
    ) -> bool:
        deadline = monotonic() + min(
            FIRST_FREE_ACCESS_PROOF_TIMEOUT_MS, PAGE_CHANGE_TIMEOUT_MS
        ) / 1_000
        while True:
            try:
                value = await page.evaluate(
                    r"""(args) => {
                      const visible = element => {
                        if (!element || element.getClientRects().length === 0) return false;
                        for (let node = element; node; node = node.parentElement) {
                          const style = getComputedStyle(node);
                          if (node.hidden || style.display === 'none' || style.visibility === 'hidden' ||
                              style.visibility === 'collapse' || Number(style.opacity) === 0) return false;
                        }
                        const box = element.getBoundingClientRect();
                        return box.width > 0 && box.height > 0;
                      };
                      const counters = [...document.querySelectorAll('body *')].filter(node =>
                        node.children.length === 0 && /^\s*[1-9][0-9]*\s*\/\s*[1-9][0-9]*\s*$/.test(node.innerText || ''));
                      const counterText = counters.length === 1
                        ? (counters[0].innerText || '').trim() : '';
                      const counterMatch = /^\s*([1-9][0-9]*)\s*\/\s*([1-9][0-9]*)\s*$/.exec(counterText);
                      const current = counterMatch ? Number(counterMatch[1]) : null;
                      const roots = [...document.querySelectorAll('.pages#content')];
                      const root = roots.length === 1 ? roots[0] : null;
                      const children = root ? [...root.children] : [];
                      const bodyNodes = children.filter(node => /^content-p[1-9][0-9]*$/.test(node.id));
                      const bodyPageIds = bodyNodes.map(node => Number(node.id.slice('content-p'.length)));
                      const visibleBodyPageIds = bodyNodes.filter(visible).map(node =>
                        Number(node.id.slice('content-p'.length)));
                      const auxiliaryIdsKnown = children.filter(node => !/^content-p[1-9][0-9]*$/.test(node.id))
                        .every(node => ['ads', 'recommend', 'rental'].includes(node.id) ||
                          /^banners-p(?:notice_banner|after_viewer)_[1-9][0-9]*$/.test(node.id));
                      const gateNodes = [...document.querySelectorAll(
                        '[role="dialog"],[aria-modal="true"],dialog,[class*="modal" i],[class*="alert" i]')]
                        .filter(visible);
                      const accessGateVisible = gateNodes.some(node => {
                        const text = (node.innerText || '').replace(/\s+/g, ' ').trim();
                        if (text === args.completionNotice) return false;
                        return /\u521d\u56de\u7121\u6599|\u30c1\u30b1\u30c3\u30c8|\u30dd\u30a4\u30f3\u30c8|\u30ec\u30f3\u30bf\u30eb|\u8cfc\u5165|\u30ed\u30b0\u30a4\u30f3|\u4f1a\u54e1\u767b\u9332|\u7121\u6599\u306f1\u65e5\u3067\u8aad\u3081\u308b\u6570/.test(text);
                      });
                      const noticeCount = [...document.querySelectorAll('body *')].filter(element =>
                        element.children.length === 0 && visible(element) &&
                        (element.innerText || '').trim() === args.completionNotice).length;
                      return {
                        currentUrl: location.href,
                        counterCount: counters.length,
                        counterText,
                        pageContainerCount: roots.length,
                        bodyPageIds,
                        visibleBodyPageIds,
                        auxiliaryIdsKnown,
                        accessGateVisible,
                        completionNoticeCount: noticeCount,
                        currentPage: current
                      };
                    }""",
                    {
                        "completionNotice": completion_notice
                    },
                )
            except PlaywrightError:
                return False
            if isinstance(value, dict):
                current_url = value.get("currentUrl")
                current_page_url = page.url
                same_expected_viewer = (
                    isinstance(current_url, str)
                    and current_page_url == current_url
                    and parse_yanmaga_viewer_url(current_url) == expected
                )
                notice_count = value.get("completionNoticeCount")
                if not same_expected_viewer:
                    self._first_free_completion_notice_seen = False
                elif notice_count == 1:
                    self._first_free_completion_notice_seen = True
                counter = parse_yanmaga_page_counter(value.get("counterText"))
                body_ids = value.get("bodyPageIds")
                visible_ids = value.get("visibleBodyPageIds")
                if (
                    same_expected_viewer
                    and value.get("counterCount") == 1
                    and value.get("pageContainerCount") == 1
                    and counter is not None
                    and counter[1] <= MAX_BODY_PAGES
                    and value.get("currentPage") == counter[0]
                    and isinstance(body_ids, list)
                    and bool(body_ids)
                    and all(
                        type(index) is int and 1 <= index <= MAX_BODY_PAGES
                        for index in body_ids
                    )
                    and len(set(body_ids)) == len(body_ids)
                    and isinstance(visible_ids, list)
                    and all(type(index) is int for index in visible_ids)
                    and counter[0] in visible_ids
                    and value.get("auxiliaryIdsKnown") is True
                    and value.get("accessGateVisible") is False
                    and notice_count in {0, 1}
                    and self._first_free_completion_notice_seen
                ):
                    return True
            remaining = deadline - monotonic()
            if remaining <= 0:
                return False
            await page.wait_for_timeout(min(RENDER_POLL_MS, max(1, int(remaining * 1_000))))

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
            "rentalWaitCount",
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
            rental_wait_count=int(raw["rentalWaitCount"]),
            rental_wait_label=(
                raw.get("rentalWaitLabel")
                if isinstance(raw.get("rentalWaitLabel"), str)
                else None
            ),
            rental_wait_clock_src=(
                raw.get("rentalWaitClockSrc")
                if isinstance(raw.get("rentalWaitClockSrc"), str)
                else None
            ),
            rental_wait_presented=raw.get("rentalWaitPresented") is True,
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
            snapshot.rental_wait_count,
            snapshot.rental_wait_label,
            snapshot.rental_wait_clock_src,
            snapshot.rental_wait_presented,
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
        wait_countdown_boundary = self._wait_countdown_matches_immediate_next_row(
            snapshot
        )
        if not (valid_next or registration_boundary or wait_countdown_boundary):
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

    def _wait_countdown_matches_immediate_next_row(
        self, snapshot: _ReaderSnapshot
    ) -> bool:
        if (
            snapshot.rental_wait_count != 1
            or not snapshot.rental_wait_presented
            or snapshot.rental_wait_clock_src != _WAIT_END_CLOCK_SRC
            or _WAIT_END_LABEL.fullmatch(snapshot.rental_wait_label or "") is None
            or snapshot.rental_next_count != 0
            or snapshot.rental_signup_count != 0
            or self._listing_rows is None
        ):
            return False

        expected = self._require_expected()
        current_indices = [
            index
            for index, row in enumerate(self._listing_rows)
            if row.episode_id == expected.episode_id
        ]
        if len(current_indices) != 1:
            return False
        next_index = current_indices[0] + 1
        if next_index >= len(self._listing_rows):
            return False
        next_row = self._listing_rows[next_index]
        next_route = parse_yanmaga_episode_url(next_row.url)
        return (
            next_row.wait_free_marker
            and not next_row.free_marker
            and not next_row.first_free_marker
            and not next_row.red_marker_present
            and not next_row.known_restricted
            and next_route is not None
            and next_route.slug == expected.slug
            and next_route.episode_id == next_row.episode_id
            and sum(row.episode_id == next_row.episode_id for row in self._listing_rows) == 1
            and snapshot.rental_title is not None
            and " ".join(snapshot.rental_title.split()) == next_row.title
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
        try:
            return await self._detect_state_impl(page)
        except BaseException:
            await self._dispose_native_observer(page)
            raise

    async def _detect_state_impl(self, page: Page) -> PageState:
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
            await self._dispose_native_observer(page)
            return PageState.END
        visible_indices = tuple(sorted(page.index for page in snapshot.visible_pages))
        if any(index not in self._captured_indices for index in visible_indices):
            return PageState.CONTENT
        if self._advance_pending:
            return PageState.LOADING
        raise UnknownPageStateError("Yanmaga viewer has no uncaptured body page")

    async def get_capture_target(self, page: Page) -> Locator:
        try:
            targets = await self.get_capture_targets(page)
            if len(targets) != 1:
                raise UnknownPageStateError("Yanmaga screen is a spread; use all capture targets")
            return targets[0]
        except BaseException:
            await self._dispose_native_observer(page)
            raise

    async def get_capture_targets(self, page: Page) -> tuple[Locator, ...]:
        try:
            return await self._get_capture_targets_impl(page)
        except BaseException:
            await self._dispose_native_observer(page)
            raise

    async def _get_capture_targets_impl(self, page: Page) -> tuple[Locator, ...]:
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
        try:
            return await self._capture_page_impl(page)
        except BaseException:
            await self._dispose_native_observer(page)
            raise

    async def _capture_page_impl(self, page: Page) -> tuple[CaptureResult, ...] | None:
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
        native_outcomes: list[NativeCaptureOutcome] = []
        fallback_reason: str | None = None
        if self._native_observer_installed:
            for index in target_indices:
                outcome = await capture_yanmaga_native_webp(
                    page, f"content-p{index}"
                )
                native_outcomes.append(outcome)
                if outcome.capture is None:
                    fallback_reason = outcome.reason
                    break
        else:
            fallback_reason = "native_observer_not_installed"

        native_group = (
            fallback_reason is None
            and len(native_outcomes) == len(target_indices)
            and all(outcome.capture is not None for outcome in native_outcomes)
        )
        if native_group and not await self._native_group_proof_is_current(
            page, target_indices, native_outcomes
        ):
            native_group = False
            fallback_reason = "native_capture_group_proof_changed"
        captures: list[CaptureResult] = []
        captured_now: list[int] = []
        for target_position, target in enumerate(targets):
            match = _PAGE_ID.fullmatch((await target.get_attribute("id")) or "")
            if match is None:
                raise UnknownPageStateError("Yanmaga capture target lost its native page ID")
            index = int(match.group("index"))
            proof = by_index.get(index)
            if proof is None or not proof.visible or proof.partial or not proof.center_owned:
                raise UnknownPageStateError("Yanmaga rendered page visibility proof changed before capture")
            if not self._segments_form_observed_page(proof):
                raise UnknownPageStateError("Yanmaga rendered page proof changed before capture")
            result = (
                native_outcomes[target_position].capture
                if native_group
                else await capture_locator(target)
            )
            if result is None:
                raise UnknownPageStateError("Yanmaga native capture group is incomplete")
            natural_width = max(segment.natural_width for segment in proof.segments)
            valid_dimensions = (
                result.width == 1125 and result.height == 1600
                if native_group
                else result.width is not None
                and result.height == 1800
                and result.width >= natural_width
            )
            if not valid_dimensions:
                raise UnknownPageStateError(
                    "Yanmaga capture dimensions differ from the verified page profile"
                )
            captures.append(result)
            captured_now.append(index)
        if captured_now != list(range(len(self._captured_indices) + 1, len(self._captured_indices) + 1 + len(captured_now))):
            raise UnknownPageStateError("Yanmaga capture buffer is not sequential")
        after = await self._wait_for_stable_snapshot(
            page, timeout_ms=PAGE_CHANGE_TIMEOUT_MS
        )
        if self._snapshot_signature(after) != self._snapshot_signature(snapshot):
            raise UnknownPageStateError("Yanmaga reader changed while page pixels were captured")
        if native_group and not await self._native_group_proof_is_current(
            page, target_indices, native_outcomes
        ):
            native_group = False
            fallback_reason = "native_capture_group_proof_changed_before_return"
            captures = []
            for target, index in zip(targets, target_indices, strict=True):
                rendered = await capture_locator(target)
                proof = by_index[index]
                natural_width = max(segment.natural_width for segment in proof.segments)
                if (
                    rendered.width is None
                    or rendered.width < natural_width
                    or rendered.height != 1800
                ):
                    raise UnknownPageStateError(
                        "Yanmaga rendered fallback dimensions differ from the verified page profile"
                    )
                captures.append(rendered)
            fallback_snapshot = await self._wait_for_stable_snapshot(
                page, timeout_ms=PAGE_CHANGE_TIMEOUT_MS
            )
            if self._snapshot_signature(fallback_snapshot) != self._snapshot_signature(snapshot):
                raise UnknownPageStateError(
                    "Yanmaga reader changed while fallback pixels were captured"
                )
        for index in target_indices:
            await release_yanmaga_native_page(page, f"content-p{index}")
        method = (
            "native_pre_jpeg_lossless_webp"
            if native_group
            else "rendered_dom_body_wrapper_png"
        )
        self._last_capture_group = {
            "group_method": method,
            "page_indices": list(target_indices),
            "pages": [
                {
                    "page_index": index,
                    "mime_type": capture.mime_type,
                    "width": capture.width,
                    "height": capture.height,
                    "method": method,
                }
                for index, capture in zip(captured_now, captures, strict=True)
            ],
            "fallback_reason": None if native_group else fallback_reason,
        }
        self._captured_indices.extend(captured_now)
        return tuple(captures)

    @staticmethod
    async def _native_group_proof_is_current(
        page: Page,
        indices: tuple[int, ...],
        outcomes: list[NativeCaptureOutcome],
    ) -> bool:
        if len(indices) != len(outcomes):
            return False
        proofs: list[tuple[str, int]] = []
        for index, outcome in zip(indices, outcomes, strict=True):
            if outcome.capture is None or outcome.proof_token is None:
                return False
            proofs.append((f"content-p{index}", outcome.proof_token))
        return await verify_yanmaga_native_group(page, proofs)

    async def get_content_identity(self, page: Page) -> ContentIdentity:
        try:
            return await self._get_content_identity_impl(page)
        except BaseException:
            await self._dispose_native_observer(page)
            raise

    async def _get_content_identity_impl(self, page: Page) -> ContentIdentity:
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
        try:
            return await self._get_content_context_impl(page)
        except BaseException:
            await self._dispose_native_observer(page)
            raise

    async def _get_content_context_impl(self, page: Page) -> ContentContext:
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
        try:
            await self._go_next_impl(page)
        except BaseException:
            await self._dispose_native_observer(page)
            raise

    async def _go_next_impl(self, page: Page) -> None:
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
            await self._dispose_native_observer(page)
            return
        if self._native_observer_installed:
            await activate_yanmaga_native_observer(page)
        self._advance_pending = True
        await page.keyboard.press("ArrowLeft")

    async def wait_for_change(
        self, page: Page, previous_identity: ContentIdentity | None
    ) -> None:
        try:
            await self._wait_for_change_impl(page, previous_identity)
        except BaseException:
            await self._dispose_native_observer(page)
            raise

    async def _wait_for_change_impl(
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
        try:
            return await self._collect_debug_metadata_impl(page)
        except BaseException:
            await self._dispose_native_observer(page)
            raise

    async def _collect_debug_metadata_impl(self, page: Page) -> dict[str, object]:
        snapshot = await self._read_snapshot(page)
        visible = snapshot.visible_pages if snapshot is not None else ()
        group = dict(self._last_capture_group)
        native_group = group.get("group_method") == "native_pre_jpeg_lossless_webp"
        metadata: dict[str, object] = {
            "capture_provenance": (
                "pre_jpeg_viewer_canvas_composition"
                if native_group
                else "rendered_dom_body_wrapper"
            ),
            "first_free_release_state": self._first_free_release_state,
            "capture_method": group.get("group_method", "capture_not_recorded"),
            "source_native_bytes_used": False,
            "source_native_pixels_used": native_group,
            "capture_viewport": f"{VIEWPORT_WIDTH}x{VIEWPORT_HEIGHT}",
            "source_segment_count": 3,
            "source_segment_widths": sorted(
                {segment.natural_width for body_page in visible for segment in body_page.segments}
            ),
            "capture_group": group,
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
