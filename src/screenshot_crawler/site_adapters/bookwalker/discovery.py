"""BookWalker series-scoped Discovery adapter."""

from __future__ import annotations

import re
from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass
from enum import StrEnum
from urllib.parse import urljoin, urlparse

from playwright.async_api import Error as PlaywrightError
from playwright.async_api import Locator, Page
from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from screenshot_crawler.discovery.base import DiscoveryAdapter
from screenshot_crawler.discovery.models import (
    DiscoveredItem,
    DiscoveredRecord,
    DiscoveredSource,
    DiscoveryMode,
    DiscoverySourceSnapshot,
    IncrementalStopDecision,
)
from screenshot_crawler.discovery.service import DiscoveryIncompleteError
from screenshot_crawler.site_adapters.bookwalker.adapter import (
    clean_bookwalker_title,
    split_bookwalker_title,
)
from screenshot_crawler.site_adapters.bookwalker.reader_controls import (
    ReaderControlKind,
    classify_reader_control,
)
from screenshot_crawler.watchlist.models import WatchlistTarget

SERIES_LIST_SELECTOR = "#js-series-list"
WAIT_TIMEOUT_MS = 10_000
POLL_INTERVAL_MS = 100
PRODUCT_CONTROL_WAIT_TIMEOUT_MS = 5_000
MAX_LIST_PAGES = 200
MAX_PRODUCTS = 5_000

_SERIES_PATH = re.compile(r"^/series/(?P<series_id>\d+)/list/?$", re.IGNORECASE)
_PRODUCT_PATH = re.compile(
    r"^/de(?P<external_id>[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})/?$",
    re.IGNORECASE,
)
_PAGINATION_LABELS = frozenset({"次へ", "もっと見る", "さらに表示"})
_PAGINATION_SELECTOR = (
    'a[rel="next"], button[rel="next"], '
    '[aria-label="次へ"], [aria-label="もっと見る"], '
    '[data-testid="pagination-next"]'
)
_SPECIAL_MARKER_SELECTOR = (
    "[data-category], [data-product-type], [data-badge], .badge"
)


@dataclass(frozen=True, slots=True)
class BookWalkerSeriesParts:
    series_id: str


@dataclass(frozen=True, slots=True)
class BookWalkerListedProduct:
    external_id: str
    url: str
    title: str | None = None
    special: bool = False


BookWalkerProductParts = BookWalkerListedProduct


class BookWalkerAccountState(StrEnum):
    """Account state observed from explicit BookWalker account UI."""

    READY = "ready"
    LOGGED_OUT = "logged_out"
    AMBIGUOUS = "ambiguous"


def classify_bookwalker_account_state(
    metadata: Mapping[str, object],
) -> BookWalkerAccountState:
    """Classify only explicit account/header evidence.

    A member-domain link or arbitrary body text is intentionally ignored. The
    browser-side probe supplies booleans limited to account/header UI and
    authentication forms/challenges.
    """

    if any(
        metadata.get(field) is True
        for field in ("login_cta", "login_form", "password_input")
    ):
        return BookWalkerAccountState.LOGGED_OUT
    if metadata.get("auth_challenge") is True:
        return BookWalkerAccountState.AMBIGUOUS
    return BookWalkerAccountState.READY


def is_bookwalker_special_title(title: str | None) -> bool:
    """Return whether a title starts with an explicit special-product prefix."""

    normalized = (title or "").strip()
    return bool(re.match(r"^(?:【(?:購入)?特典】|〖(?:購入)?特典〗)", normalized))


def _bookwalker_host(url: str) -> bool:
    parsed = urlparse(url)
    return parsed.scheme.lower() == "https" and parsed.hostname in {
        "bookwalker.jp",
        "www.bookwalker.jp",
    }


def parse_bookwalker_series_url(url: str) -> BookWalkerSeriesParts | None:
    """Parse only the explicitly supported BookWalker series-list URL."""

    if not _bookwalker_host(url):
        return None
    match = _SERIES_PATH.fullmatch(urlparse(url).path)
    if match is None:
        return None
    return BookWalkerSeriesParts(series_id=match.group("series_id"))


def parse_bookwalker_product_url(url: str) -> BookWalkerProductParts | None:
    """Parse a canonical BookWalker ``/de<uuid>/`` product URL."""

    if not _bookwalker_host(url):
        return None
    parsed = urlparse(url)
    match = _PRODUCT_PATH.fullmatch(parsed.path)
    if match is None:
        return None
    external_id = match.group("external_id").lower()
    return BookWalkerProductParts(
        external_id=external_id,
        url=f"https://bookwalker.jp/de{external_id}/",
    )


def _bookwalker_order_label(number: int) -> str:
    width = 3 if number >= 100 else 2
    return f"第{number:0{width}d}巻"


def parse_bookwalker_order(
    raw_title: str | None,
    *,
    special: bool = False,
) -> tuple[str | None, str | None]:
    """Return a safe numeric order and display label for a product title."""

    cleaned = clean_bookwalker_title(raw_title)
    if special:
        return None, cleaned or None

    hash_match = re.search(r"(?:^|\s)#(?P<number>\d+)(?=\s|$)", cleaned)
    if hash_match:
        return str(int(hash_match.group("number"))), _bookwalker_order_label(
            int(hash_match.group("number"))
        )

    cleaned_title, volume_label = split_bookwalker_title(cleaned)
    if volume_label:
        match = re.search(r"\d+", volume_label)
        if match:
            return str(int(match.group(0))), volume_label

    volume_match = re.search(r"第\s*(?P<number>\d+)\s*巻", cleaned)
    if volume_match:
        number = int(volume_match.group("number"))
        return str(number), _bookwalker_order_label(number)

    volume_match = re.search(r"(?<!\d)(?P<number>\d+)\s*巻", cleaned)
    if volume_match:
        number = int(volume_match.group("number"))
        return str(number), _bookwalker_order_label(number)
    return None, cleaned_title or None


def map_bookwalker_access_mode(controls: list[dict[str, object]]) -> str:
    """Map observed reader controls to the Catalog access modes."""

    classifications = {classify_reader_control(control) for control in controls}
    if ReaderControlKind.OWNED in classifications:
        return "owned"
    if ReaderControlKind.MARUYOMI in classifications:
        return "quota"
    if ReaderControlKind.TRIAL in classifications:
        return "paid"
    return "unknown"


class BookWalkerDiscoveryAdapter(DiscoveryAdapter):
    """Enumerate products from one explicit BookWalker series list."""

    async def iter_records(
        self,
        page: Page,
        target: WatchlistTarget,
        mode: DiscoveryMode,
    ) -> AsyncIterator[DiscoveredRecord]:
        del mode
        if parse_bookwalker_series_url(target.url) is None:
            raise DiscoveryIncompleteError(
                "Watchlist target must be a BookWalker /series/<id>/list/ URL"
            )

        try:
            products, series_title = await self._collect_series_products(page, target.url)
        except (PlaywrightError, TimeoutError) as exc:
            raise DiscoveryIncompleteError(
                "BookWalker series listing did not load or advance"
            ) from exc

        canonical_title = (target.label or "").strip() or series_title
        if not canonical_title:
            raise DiscoveryIncompleteError("BookWalker series title was not found")

        for product in products:
            try:
                product_data = await self._observe_product(page, product)
            except (PlaywrightError, TimeoutError) as exc:
                raise DiscoveryIncompleteError(
                    f"BookWalker product page did not load: {product.external_id}"
                ) from exc
            product_title = product.title or product_data["title"]
            order_key, order_label = parse_bookwalker_order(
                product_title,
                special=product.special,
            )
            yield DiscoveredRecord(
                item=DiscoveredItem(
                    canonical_title=canonical_title,
                    author=product_data["author"],
                    genre=product_data["genre"],
                    kind="book",
                    order_key=order_key,
                    order_label=order_label,
                ),
                source=DiscoveredSource(
                    external_id=product.external_id,
                    url=product.url,
                    access_mode=map_bookwalker_access_mode(product_data["controls"]),
                    available=True,
                ),
            )

    def reconcile_access_mode(
        self,
        observed_access_mode: str,
        previous: DiscoverySourceSnapshot | None,
        target: WatchlistTarget,
    ) -> str:
        """Preserve BookWalker's stable owned/quota access observations."""

        self._ensure_scope(previous, target)
        if previous is None:
            return observed_access_mode
        if previous.access_mode == "owned":
            return "owned"
        if previous.access_mode == "quota" and observed_access_mode in {
            "paid",
            "unknown",
        }:
            return "quota"
        return observed_access_mode

    def incremental_stop_decision(
        self,
        record: DiscoveredRecord,
        previous: DiscoverySourceSnapshot | None,
        target: WatchlistTarget,
    ) -> IncrementalStopDecision:
        """Stop only at a run-start owned/quota stable boundary."""

        del record
        self._ensure_scope(previous, target)
        if previous is not None and previous.access_mode in {"owned", "quota"}:
            return IncrementalStopDecision.STOP
        return IncrementalStopDecision.CONTINUE

    async def _collect_series_products(
        self,
        page: Page,
        target_url: str,
    ) -> tuple[list[BookWalkerListedProduct], str | None]:
        await page.goto(target_url, wait_until="domcontentloaded", timeout=WAIT_TIMEOUT_MS)
        await self._assert_account_state(page)
        series_list = await self._series_list(page)
        series_title = await self._series_title(page, series_list)
        products: list[BookWalkerListedProduct] = []
        seen_ids: set[str] = set()
        previous_signature: tuple[str, ...] | None = None

        for page_number in range(1, MAX_LIST_PAGES + 1):
            series_list = await self._series_list(page)
            current_products = await self._product_links(series_list, page.url)
            signature = tuple(product.external_id for product in current_products)
            if not signature or signature == previous_signature:
                raise DiscoveryIncompleteError(
                    "BookWalker series listing is empty or did not advance"
                )
            previous_signature = signature
            for product in current_products:
                if product.external_id in seen_ids:
                    continue
                seen_ids.add(product.external_id)
                products.append(product)
                if len(products) > MAX_PRODUCTS:
                    raise DiscoveryIncompleteError(
                        "BookWalker series listing exceeded product limit"
                    )

            control = await self._pagination_control(series_list)
            if control is None:
                return products, series_title
            if page_number == MAX_LIST_PAGES:
                raise DiscoveryIncompleteError(
                    "BookWalker series listing exceeded page limit"
                )
            await control.click(timeout=WAIT_TIMEOUT_MS)
            await self._wait_for_listing_change(page, previous_signature)

        raise DiscoveryIncompleteError("BookWalker series listing did not terminate")

    async def _series_list(self, page: Page) -> Locator:
        listing = page.locator(SERIES_LIST_SELECTOR)
        if await listing.count() != 1:
            raise DiscoveryIncompleteError(
                "BookWalker series product-list scope is not unambiguous"
            )
        if not await listing.is_visible():
            raise DiscoveryIncompleteError("BookWalker series product-list scope is hidden")
        return listing

    async def _series_title(self, page: Page, listing: Locator) -> str | None:
        for selector in ("h1", "[data-series-title]", "h2"):
            candidates = listing.locator(selector)
            for index in range(await candidates.count()):
                candidate = candidates.nth(index)
                if await candidate.is_visible():
                    title = " ".join((await candidate.inner_text()).split())
                    if title:
                        return title
        page_titles = page.locator("h1")
        for index in range(await page_titles.count()):
            candidate = page_titles.nth(index)
            if await candidate.is_visible():
                title = " ".join((await candidate.inner_text()).split())
                if title:
                    return title
        return None

    async def _product_links(
        self,
        listing: Locator,
        page_url: str,
    ) -> list[BookWalkerListedProduct]:
        cards = listing.locator("article")
        if await cards.count() == 0:
            raise DiscoveryIncompleteError(
                "BookWalker series product cards are not identifiable"
            )

        products: list[BookWalkerListedProduct] = []
        for card_index in range(await cards.count()):
            card = cards.nth(card_index)
            anchors = card.locator("a[href]")
            card_title = await self._card_title(card, anchors)
            special = await self._card_is_special(card, card_title)
            for anchor_index in range(await anchors.count()):
                href = await anchors.nth(anchor_index).get_attribute("href")
                if not href:
                    continue
                product = parse_bookwalker_product_url(urljoin(page_url, href))
                if product is not None:
                    products.append(
                        BookWalkerListedProduct(
                            external_id=product.external_id,
                            url=product.url,
                            title=card_title,
                            special=special,
                        )
                    )
        return products

    @staticmethod
    async def _card_title(card: Locator, anchors: Locator) -> str | None:
        for selector in ("h3", "h2", "[data-title]", "[data-product-title]"):
            candidates = card.locator(selector)
            for index in range(await candidates.count()):
                candidate = candidates.nth(index)
                if await candidate.is_visible():
                    title = " ".join((await candidate.inner_text()).split())
                    if title:
                        return title
        for index in range(await anchors.count()):
            anchor = anchors.nth(index)
            if await anchor.is_visible():
                title = " ".join((await anchor.inner_text()).split())
                if title:
                    return title
        return None

    @staticmethod
    async def _card_is_special(card: Locator, card_title: str | None) -> bool:
        markers = card.locator(_SPECIAL_MARKER_SELECTOR)
        for index in range(await markers.count()):
            marker = markers.nth(index)
            if await marker.is_visible():
                text = " ".join((await marker.inner_text()).split())
                if "特典" in text:
                    return True
        return is_bookwalker_special_title(card_title)

    async def _pagination_control(self, listing: Locator) -> Locator | None:
        matches: list[Locator] = []
        controls = listing.locator(_PAGINATION_SELECTOR)
        for index in range(await controls.count()):
            control = controls.nth(index)
            if await control.is_visible() and not await self._is_disabled(control):
                matches.append(control)

        if not matches:
            buttons = listing.locator("a, button")
            for index in range(await buttons.count()):
                control = buttons.nth(index)
                if not await control.is_visible() or await self._is_disabled(control):
                    continue
                label = " ".join((await control.inner_text()).split())
                if label in _PAGINATION_LABELS:
                    matches.append(control)
        if len(matches) > 1:
            raise DiscoveryIncompleteError(
                "BookWalker series pagination control is ambiguous"
            )
        return matches[0] if matches else None

    async def _wait_for_listing_change(
        self,
        page: Page,
        previous_signature: tuple[str, ...],
    ) -> None:
        elapsed = 0
        while elapsed < WAIT_TIMEOUT_MS:
            listing = await self._series_list(page)
            signature = tuple(
                product.external_id
                for product in await self._product_links(listing, page.url)
            )
            if signature and signature != previous_signature:
                return
            await page.wait_for_timeout(POLL_INTERVAL_MS)
            elapsed += POLL_INTERVAL_MS
        raise DiscoveryIncompleteError("BookWalker series pagination did not advance")

    async def _observe_product(
        self,
        page: Page,
        product: BookWalkerListedProduct,
    ) -> dict[str, object]:
        await page.goto(product.url, wait_until="domcontentloaded", timeout=WAIT_TIMEOUT_MS)
        final_product = parse_bookwalker_product_url(page.url)
        if final_product is None or final_product.external_id != product.external_id:
            raise DiscoveryIncompleteError(
                f"BookWalker product identity changed: {product.external_id}"
            )
        await self._assert_account_state(page)

        latest_data: dict[str, object] | None = None
        elapsed = 0
        while elapsed < PRODUCT_CONTROL_WAIT_TIMEOUT_MS:
            await self._assert_account_state(page)
            data = await page.evaluate(_PRODUCT_METADATA_SCRIPT)
            latest_data = data
            if data["title"] and data["controls"]:
                return data
            await page.wait_for_timeout(POLL_INTERVAL_MS)
            elapsed += POLL_INTERVAL_MS
        if latest_data is None or not latest_data["title"]:
            raise DiscoveryIncompleteError(
                f"BookWalker product metadata was not observed: {product.external_id}"
            )
        return latest_data

    @staticmethod
    async def _assert_account_state(page: Page) -> None:
        state = classify_bookwalker_account_state(
            await page.evaluate(_ACCOUNT_STATE_SCRIPT)
        )
        if state is not BookWalkerAccountState.READY:
            raise DiscoveryIncompleteError(
                f"BookWalker account state is {state.value}"
            )

    @staticmethod
    async def _is_disabled(locator: Locator) -> bool:
        try:
            if await locator.is_disabled():
                return True
        except (PlaywrightTimeoutError, TimeoutError):
            return True
        return (await locator.get_attribute("aria-disabled")) == "true"

    @staticmethod
    def _ensure_scope(
        previous: DiscoverySourceSnapshot | None,
        target: WatchlistTarget,
    ) -> None:
        if (
            previous is not None
            and previous.discovery_key is not None
            and previous.discovery_key != target.key
        ):
            raise DiscoveryIncompleteError(
                "BookWalker source belongs to a different Discovery scope"
            )


_ACCOUNT_STATE_SCRIPT = """
() => {
  const visible = element => {
    const style = window.getComputedStyle(element);
    return style.display !== 'none' && style.visibility !== 'hidden' &&
      (element.offsetWidth > 0 || element.offsetHeight > 0 || element.getClientRects().length > 0);
  };
  const textOf = element => (element.innerText || element.getAttribute('aria-label') ||
    element.getAttribute('title') || '').replace(/\\s+/g, ' ').trim();
  const roots = document.querySelectorAll(
    'header, [role="banner"], #header, #globalHeader, [data-testid="header"]'
  );
  let loginCta = false;
  for (const root of roots) {
    for (const element of root.querySelectorAll('a, button, [role="link"], [role="button"]')) {
      if (visible(element) && textOf(element).includes('ログイン')) {
        loginCta = true;
      }
    }
  }
  const passwordInput = [...document.querySelectorAll('input[type="password"]')]
    .some(visible);
  const loginForm = [...document.querySelectorAll('form')].some(form => {
    if (!visible(form)) return false;
    return [...form.querySelectorAll(
      'input[type="password"], input[type="email"], input[autocomplete="username"], input[name="j_username"]'
    )].some(visible);
  });
  const authChallenge = [...document.querySelectorAll(
    '[id*="captcha" i], [class*="captcha" i], iframe[src*="captcha" i], [aria-label*="認証"]'
  )].some(visible);
  return {login_cta: loginCta, login_form: loginForm, password_input: passwordInput,
    auth_challenge: authChallenge};
}
"""


_PRODUCT_METADATA_SCRIPT = """
() => {
  const visible = element => {
    const style = window.getComputedStyle(element);
    return style.display !== 'none' && style.visibility !== 'hidden' &&
      (element.offsetWidth > 0 || element.offsetHeight > 0 || element.getClientRects().length > 0);
  };
  const textOf = element => (element.innerText || element.getAttribute('aria-label') ||
    element.getAttribute('title') || '').trim();
  const selectors = [
    '#js-read-check a, #js-read-check button, #js-read-check [role="button"], #js-read-check [data-action-label]',
    '#js-subscription-check a, #js-subscription-check button, #js-subscription-check [role="button"], #js-subscription-check [data-action-label]',
    'a[href*="viewer.bookwalker.jp"]',
    '[data-action-label="reading"], [data-action-label="read"], [data-action-label="trial_reading"], [data-action-label="read_maruyomi"]'
  ];
  const controls = [];
  const seen = new Set();
  for (const selector of selectors) {
    for (const element of document.querySelectorAll(selector)) {
      if (!visible(element) || seen.has(element)) continue;
      seen.add(element);
      controls.push({
        text: textOf(element),
        action: element.getAttribute('data-action-label'),
        href: element.href || element.getAttribute('data-href') || element.getAttribute('data-url') || '',
        uuid: element.getAttribute('data-uuid')
      });
    }
  }
  const title = document.querySelector('h1.t-c-product-main-data__title, h1');
  const author = document.querySelector('.t-c-product-main-data__authors');
  let genre = document.querySelector('.t-c-product-main-data__genre, .t-c-product-main-data__category');
  if (!genre) {
    for (const dt of document.querySelectorAll('dt')) {
      if (/カテゴリ|ジャンル|category|genre/i.test(textOf(dt))) {
        genre = dt.nextElementSibling;
        break;
      }
    }
  }
  return {
    title: title && visible(title) ? textOf(title) : '',
    author: author && visible(author) ? textOf(author) : null,
    genre: genre && visible(genre) ? textOf(genre) : null,
    controls
  };
}
"""
