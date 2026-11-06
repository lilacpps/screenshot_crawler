"""Full, purchased-only Discovery for ebookjapan series listings."""

from __future__ import annotations

import re
import unicodedata
from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import Any, ClassVar
from urllib.parse import urlsplit

from playwright.async_api import Error as PlaywrightError
from playwright.async_api import Page

from screenshot_crawler.core.access_guard import AccessGuard, AccessProfile
from screenshot_crawler.discovery.base import DiscoveryAdapter
from screenshot_crawler.discovery.models import (
    DiscoveredItem,
    DiscoveredRecord,
    DiscoveredSource,
    DiscoveryMode,
)
from screenshot_crawler.discovery.service import DiscoveryIncompleteError
from screenshot_crawler.registration.models import UrlResolution, resolved_url
from screenshot_crawler.watchlist.models import WatchlistTarget

SITE_HOST = "ebookjapan.yahoo.co.jp"
SITE_ORIGIN = f"https://{SITE_HOST}"
WAIT_TIMEOUT_MS = 15_000
SCROLL_TIMEOUT_MS = 20_000
SCROLL_POLL_MS = 650
STABLE_BOTTOM_READS = 3
MAX_CARDS = 2_000
MAX_SOURCE_RESPONSE_BYTES = 32 * 1024 * 1024

_LIST_PATH = re.compile(r"^https://ebookjapan\.yahoo\.co\.jp/books/all/(?P<series>[1-9][0-9]*)/$")
_PRODUCT_PATH_TEMPLATE = "/books/{series}/"
_PRODUCT_ID = re.compile(r"^/books/(?P<series>[1-9][0-9]*)/(?P<product>A[0-9]+)/$")
_VOLUME_SUFFIX = re.compile(
    r"(?:\s*(?P<volume>[0-9]{1,3})\s*巻|\s*[（(]\s*(?P<paren>[0-9]{1,3})\s*[）)])\s*$"
)
_CONFLICTING_RIGHT = re.compile(r"レンタル|無料で読む|試し読み|読み放題|期限付き|無料巻")

_FULL_LISTING_JS = r"""() => {
  const host = 'ebookjapan.yahoo.co.jp';
  const visible = (element, stopAt = document.documentElement) => {
    if (!element || element.getClientRects().length === 0) return false;
    let node = element;
    while (node) {
      if (node.hidden) return false;
      const style = getComputedStyle(node);
      if (style.display === 'none' || style.visibility === 'hidden'
          || style.visibility === 'collapse' || Number(style.opacity) === 0) return false;
      if (node === stopAt) return true;
      node = node.parentElement;
    }
    return false;
  };
  const safePath = href => {
    try {
      const url = new URL(href, location.href);
      return url.origin === `https://${host}` && !url.search && !url.hash
        && !url.username && !url.password ? url.pathname : null;
    } catch { return null; }
  };
  const headers = [...document.querySelectorAll('.page-books-all__list-header')]
    .filter(element => visible(element));
  let declaredTotal = null;
  let oldestFirst = false;
  let sortControlCount = 0;
  if (headers.length === 1) {
    const resultLabels = [...headers[0].querySelectorAll('.search-header__result')]
      .filter(element => visible(element))
      .map(element => (element.innerText || element.textContent || '').trim().normalize('NFKC').replace(/\s+/g, ' '));
    if (resultLabels.length === 1) {
      const match = resultLabels[0].match(/^(?:全\s*)?([0-9]+)\s*冊$/);
      if (match) declaredTotal = Number(match[1]);
    }
    const radios = [...headers[0].querySelectorAll('input[type="radio"]')];
    const checked = radios.filter(element => element.checked);
    sortControlCount = radios.length;
    if (checked.length === 1 && visible(checked[0].closest('.search-filter__item') || checked[0])) {
      const item = checked[0].closest('.search-filter__item');
      const label = (item?.innerText || checked[0].labels?.[0]?.innerText || '')
        .trim().normalize('NFKC').replace(/\s+/g, ' ');
      oldestFirst = label === '1巻から';
    }
  }
  const headings = [...document.querySelectorAll('.page-books-all__heading')]
    .filter(element => visible(element));
  const seriesTitle = headings.length === 1
    ? (headings[0].innerText || headings[0].textContent || '').trim().replace(/\s+/g, ' ').slice(0, 160)
    : null;
  const accountUsers = [...document.querySelectorAll('.account__user')]
    .filter(element => visible(element));
  const accountLinks = accountUsers.length === 1
    ? [...accountUsers[0].querySelectorAll('a[href]')].filter(element => safePath(element.href) === '/mypage/')
    : [];
  const accountAuthenticated = accountUsers.length === 1
    && (accountUsers[0].innerText || accountUsers[0].textContent || '').trim().length > 0
    && accountLinks.length === 1 && visible(accountLinks[0]);
  const cards = [...document.querySelectorAll('.book-list__item')];
  const rows = cards.map((card, index) => {
    const cardRect = card.getBoundingClientRect();
    const links = [...card.querySelectorAll('a.book-item[href]')];
    const titleNodes = [...card.querySelectorAll('.book-caption__title')].filter(element => visible(element, card));
    const badgeNodes = [...card.querySelectorAll('span.book-caption__tagtext')];
    const badges = badgeNodes.map(element => ({
      text: (element.innerText || element.textContent || '').trim().normalize('NFKC').replace(/\s+/g, ' '),
      visible: visible(element, card),
    })).filter(badge => badge.text);
    const prices = [...card.querySelectorAll('.book-caption__price')]
      .filter(element => visible(element, card))
      .map(element => (element.innerText || element.textContent || '').trim().normalize('NFKC').replace(/\s+/g, ' '));
    const controls = [...card.querySelectorAll('button,[role="button"]')]
      .filter(element => visible(element, card));
    const basketCount = controls.filter(control =>
      [...control.querySelectorAll('[class]')].some(icon => icon.classList.contains('font-basket-v1'))
    ).length;
    const allBadgeTexts = badges.filter(badge => badge.visible).map(badge => badge.text);
    return {
      index,
      path: links.length === 1 ? safePath(links[0].href) : null,
      linkCount: links.length,
      title: titleNodes.length === 1
        ? (titleNodes[0].innerText || titleNodes[0].textContent || '').trim().replace(/\s+/g, ' ').slice(0, 160)
        : null,
      titleCount: titleNodes.length,
      visible: visible(card) && cardRect.width > 0 && cardRect.height > 0,
      top: Math.round(cardRect.top + window.scrollY),
      left: Math.round(cardRect.left),
      badges,
      visiblePrices: prices,
      basketCount,
      conflictingRights: allBadgeTexts.filter(text => /レンタル|無料で読む|試し読み|読み放題|期限付き|無料巻/.test(text)),
    };
  });
  const domPaths = rows.map(row => row.path);
  const layoutPaths = rows.slice().sort((a, b) => a.top - b.top || a.left - b.left || a.index - b.index)
    .map(row => row.path);
  const listControlRoots = [
    ...headers,
    ...[...document.querySelectorAll('.page-books-all__bottom')].filter(element => visible(element)),
  ];
  const visibleControls = listControlRoots.flatMap(root =>
    [...root.querySelectorAll('a[href],button,[role="button"]')].filter(element => visible(element))
  );
  const controlText = visibleControls.map(element =>
    (element.innerText || element.getAttribute('aria-label') || '').trim().normalize('NFKC').replace(/\s+/g, ' ')
  );
  const paginationCount = controlText.filter(text =>
    /前へ|次へ|前のページ|次のページ/.test(text)
  ).length;
  const loadMoreCount = controlText.filter(text => /もっと見る|続きを見る|続きを表示|さらに表示/.test(text)).length;
  const canonicalLinks = [...document.querySelectorAll('link[rel="canonical"]')];
  const canonicalPath = canonicalLinks.length === 1 ? safePath(canonicalLinks[0].href) : null;
  const documentHeight = Math.max(document.documentElement.scrollHeight, document.body?.scrollHeight || 0);
  return {
    pageUrl: location.href,
    pagePath: location.pathname,
    pageHost: location.hostname,
    canonicalCount: canonicalLinks.length,
    canonicalPath,
    declaredTotal,
    oldestFirst,
    sortControlCount,
    seriesTitle,
    accountAuthenticated,
    cardCount: rows.length,
    rows,
    domPaths,
    layoutPaths,
    paginationCount,
    loadMoreCount,
    bottomReached: window.scrollY + window.innerHeight >= documentHeight - 4,
  };
}"""

_ID_SNAPSHOT_JS = r"""() => {
  const paths = [...document.querySelectorAll('.book-list__item')].map(card => {
    const links = [...card.querySelectorAll('a.book-item[href]')];
    if (links.length !== 1) return null;
    try {
      const url = new URL(links[0].href);
      return url.origin === 'https://ebookjapan.yahoo.co.jp' && !url.search && !url.hash
        ? url.pathname : null;
    } catch { return null; }
  });
  const height = Math.max(document.documentElement.scrollHeight, document.body?.scrollHeight || 0);
  return {paths, count: paths.length, bottomReached: window.scrollY + window.innerHeight >= height - 4};
}"""


def _rights_signature(payload: Mapping[str, Any]) -> tuple[object, ...]:
    """Return only public account/list identity and per-card ownership signals."""

    rows = payload.get("rows")
    if not isinstance(rows, list):
        return ()
    card_signals = []
    for row in rows:
        if not isinstance(row, Mapping):
            return ()
        badges = row.get("badges")
        card_signals.append(
            (
                row.get("path"),
                row.get("title"),
                row.get("visible"),
                tuple(
                    (badge.get("text"), badge.get("visible"))
                    for badge in badges if isinstance(badge, Mapping)
                ) if isinstance(badges, list) else (),
                tuple(row.get("visiblePrices", ())) if isinstance(row.get("visiblePrices"), list) else (),
                row.get("basketCount"),
                tuple(row.get("conflictingRights", ()))
                if isinstance(row.get("conflictingRights"), list) else (),
            )
        )
    return (
        payload.get("pageUrl"),
        payload.get("pagePath"),
        payload.get("accountAuthenticated"),
        payload.get("declaredTotal"),
        payload.get("oldestFirst"),
        tuple(payload.get("domPaths", ())) if isinstance(payload.get("domPaths"), list) else (),
        tuple(payload.get("layoutPaths", ())) if isinstance(payload.get("layoutPaths"), list) else (),
        tuple(card_signals),
    )


@dataclass(slots=True)
class _SourceNode:
    tag: str
    classes: frozenset[str]
    attrs: dict[str, str]
    children: list[_SourceNode] = field(default_factory=list)
    text: list[str] = field(default_factory=list)
    in_template: bool = False
    in_noscript: bool = False
    hidden_or_ancestor: bool = False


class _SourceListingParser(HTMLParser):
    """Retain only card structure, safe attributes and card-local label text."""

    _VOID_TAGS: ClassVar[set[str]] = {
        "area", "base", "br", "col", "embed", "hr", "img", "input", "link",
        "meta", "param", "source", "track", "wbr",
    }
    _IGNORED_TAGS: ClassVar[set[str]] = {"script", "style"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.roots: list[_SourceNode] = []
        self.stack: list[_SourceNode] = []
        self.ignored_tag: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if self.ignored_tag is not None:
            return
        if tag in self._IGNORED_TAGS:
            self.ignored_tag = tag
            return
        raw = {name: value or "" for name, value in attrs}
        classes = frozenset(raw.get("class", "").split())
        ancestors = self.stack
        in_card = "book-list__item" in classes or any(
            "book-list__item" in node.classes for node in ancestors
        )
        style = re.sub(r"\s+", "", raw.get("style", "")).lower()
        hidden_here = (
            "hidden" in raw
            or raw.get("aria-hidden", "").lower() == "true"
            or "display:none" in style
            or "visibility:hidden" in style
            or "opacity:0" in style
        )
        hidden_or_ancestor = hidden_here or any(node.hidden_or_ancestor for node in ancestors)
        relevant_attrs = {"class": raw.get("class", "")}
        if in_card:
            relevant_attrs["hidden"] = "hidden" if hidden_or_ancestor else ""
        if tag == "a" and in_card and "book-item" in classes:
            relevant_attrs["href"] = raw.get("href", "")
        node = _SourceNode(
            tag=tag,
            classes=classes,
            attrs=relevant_attrs,
            in_template=tag == "template" or any(item.in_template for item in ancestors),
            in_noscript=tag == "noscript" or any(item.in_noscript for item in ancestors),
            hidden_or_ancestor=hidden_or_ancestor,
        )
        if self.stack:
            self.stack[-1].children.append(node)
        else:
            self.roots.append(node)
        if tag not in self._VOID_TAGS:
            self.stack.append(node)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        if self.stack and self.stack[-1].tag == tag:
            self.stack.pop()

    def handle_endtag(self, tag: str) -> None:
        if self.ignored_tag is not None:
            if tag == self.ignored_tag:
                self.ignored_tag = None
            return
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index].tag == tag:
                del self.stack[index:]
                break

    def handle_data(self, data: str) -> None:
        if (
            self.ignored_tag is None
            and self.stack
            and data.strip()
            and any("book-list__item" in node.classes for node in self.stack)
        ):
            self.stack[-1].text.append(data)


@dataclass(frozen=True, slots=True)
class _SourceCardWitness:
    path: str
    external_id: str
    owned: bool


def _source_nodes(node: _SourceNode):
    for child in node.children:
        yield child
        yield from _source_nodes(child)


def _source_text(node: _SourceNode) -> str:
    value = " ".join([*node.text, *(_source_text(child) for child in node.children)])
    return _normalized(value)


def _source_path(href: str, *, series_id: str) -> str | None:
    try:
        parsed = urlsplit(href)
    except ValueError:
        return None
    if (parsed.scheme or parsed.netloc) and (
        parsed.scheme != "https" or parsed.hostname != SITE_HOST
    ):
        return None
    if parsed.query or parsed.fragment:
        return None
    match = _PRODUCT_ID.fullmatch(parsed.path)
    if match is None or match.group("series") != series_id:
        return None
    return parsed.path


def parse_ebookjapan_source_witness(
    html: str,
    *,
    series_id: str,
) -> tuple[_SourceCardWitness, ...]:
    """Parse a same-response static ownership bitset, never a full rights state.

    A static purchase badge is an expected owned bit only when it is unique and
    has no structural ambiguity. A missing badge is not proof of NOT_OWNED:
    it only permits the hydrated card to prove that state with a positive price
    and one visible basket action.
    """

    parser = _SourceListingParser()
    parser.feed(html)
    cards = [node for node in _source_nodes_from_roots(parser.roots) if "book-list__item" in node.classes]
    if not cards or len(cards) > MAX_CARDS:
        raise DiscoveryIncompleteError("ebookjapan source response has no complete card inventory")

    witnesses: list[_SourceCardWitness] = []
    for card in cards:
        if card.in_template or card.in_noscript:
            raise DiscoveryIncompleteError("ebookjapan source card is template or noscript content")
        links = [node for node in _source_nodes(card) if node.tag == "a" and "book-item" in node.classes]
        if len(links) != 1:
            raise DiscoveryIncompleteError("ebookjapan source card has ambiguous product links")
        path = _source_path(links[0].attrs.get("href", ""), series_id=series_id)
        product_match = _PRODUCT_ID.fullmatch(path) if path else None
        if path is None or product_match is None:
            raise DiscoveryIncompleteError("ebookjapan source product path is invalid or belongs to another series")

        badge_nodes = [
            node for node in _source_nodes(card)
            if node.tag == "span" and "book-caption__tagtext" in node.classes
        ]
        owned_badges = [node for node in badge_nodes if _source_text(node) == "購入済み"]
        price_nodes = [node for node in _source_nodes(card) if "book-caption__price" in node.classes]
        purchase_branch_ambiguous = any(
            node.attrs.get("hidden")
            or node.in_template
            or node.in_noscript
            for node in (card, *owned_badges, *price_nodes)
        )
        if purchase_branch_ambiguous:
            raise DiscoveryIncompleteError("ebookjapan source card has hidden or templated rights structure")
        if len(owned_badges) == 1 and len(price_nodes) == 0:
            owned = True
        elif len(owned_badges) == 0 and len(price_nodes) == 1:
            owned = False
        else:
            raise DiscoveryIncompleteError("ebookjapan source card rights branch is missing or ambiguous")
        witnesses.append(
            _SourceCardWitness(
                path=path,
                external_id=product_match.group("product"),
                owned=owned,
            )
        )

    external_ids = [witness.external_id for witness in witnesses]
    if len(external_ids) != len(set(external_ids)):
        raise DiscoveryIncompleteError("ebookjapan source response contains duplicate product IDs")
    return tuple(witnesses)


def _source_nodes_from_roots(roots: list[_SourceNode]):
    for root in roots:
        yield root
        yield from _source_nodes(root)


def _source_rights_match(
    payload: Mapping[str, Any],
    witnesses: tuple[_SourceCardWitness, ...],
) -> bool:
    rows = payload.get("rows")
    dom_paths = payload.get("domPaths")
    if (
        not isinstance(rows, list)
        or not isinstance(dom_paths, list)
        or len(rows) != len(witnesses)
        or len(dom_paths) != len(witnesses)
    ):
        return False
    for row, witness in zip(rows, witnesses, strict=True):
        if not isinstance(row, Mapping) or row.get("path") != witness.path:
            return False
        state = _classify_card(row)
        if witness.owned and state != "owned":
            return False
        if not witness.owned and state != "explicitly_not_owned":
            return False
    return dom_paths == [witness.path for witness in witnesses]


def parse_ebookjapan_series_url(url: str) -> str | None:
    """Accept only the exact canonical HTTPS full-series URL."""

    match = _LIST_PATH.fullmatch(url) if isinstance(url, str) else None
    return match.group("series") if match else None


def _normalized(text: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", text).split())


def _explicit_volume(title: str) -> tuple[str | None, str | None]:
    normalized = _normalized(title)
    match = _VOLUME_SUFFIX.search(normalized)
    if match is None:
        return None, None
    number_text = match.group("volume") or match.group("paren")
    if number_text is None:
        return None, None
    return str(int(number_text)), match.group(0).strip()


def _positive_yen_price(value: object) -> bool:
    if not isinstance(value, str):
        return False
    normalized = _normalized(value).replace(" ", "")
    match = re.fullmatch(r"([0-9][0-9,]*)円(?:\(税込\))?", normalized)
    if match is None:
        return False
    try:
        return int(match.group(1).replace(",", "")) > 0
    except ValueError:
        return False


def _classify_card(card: Mapping[str, Any]) -> str:
    if card.get("visible") is not True:
        return "unknown"
    badges = card.get("badges")
    if not isinstance(badges, list):
        return "unknown"
    visible_owned = [
        badge for badge in badges
        if isinstance(badge, Mapping)
        and badge.get("visible") is True
        and _normalized(str(badge.get("text") or "")) == "購入済み"
    ]
    visible_badge_texts = [
        _normalized(str(badge.get("text") or ""))
        for badge in badges
        if isinstance(badge, Mapping) and badge.get("visible") is True
    ]
    if any(_CONFLICTING_RIGHT.search(text) for text in visible_badge_texts):
        return "unknown"
    prices = card.get("visiblePrices")
    basket_count = card.get("basketCount")
    if not isinstance(prices, list) or type(basket_count) is not int:
        return "unknown"
    if len(visible_owned) == 1:
        return "owned" if len(prices) == 0 and basket_count == 0 else "unknown"
    if not visible_owned and len(prices) == 1 and _positive_yen_price(prices[0]) and basket_count == 1:
        return "explicitly_not_owned"
    return "unknown"


def parse_ebookjapan_listing(
    payload: object,
    *,
    series_id: str,
) -> tuple[list[DiscoveredRecord], list[DiscoveredRecord]]:
    """Validate a fully settled, authenticated listing into all/owned records."""

    if not isinstance(payload, Mapping):
        raise DiscoveryIncompleteError("ebookjapan listing snapshot is unavailable")
    if (
        payload.get("pageHost") != SITE_HOST
        or payload.get("pagePath") != f"/books/all/{series_id}/"
        or payload.get("pageUrl") != f"{SITE_ORIGIN}/books/all/{series_id}/"
        or payload.get("accountAuthenticated") is not True
        or not isinstance(payload.get("seriesTitle"), str)
        or not _normalized(payload["seriesTitle"])
    ):
        raise DiscoveryIncompleteError("ebookjapan listing identity or signed-in state is unverified")
    canonical_count = payload.get("canonicalCount")
    canonical_path = payload.get("canonicalPath")
    if canonical_count not in (0, 1) or (canonical_count == 1 and canonical_path != f"/books/all/{series_id}/"):
        raise DiscoveryIncompleteError("ebookjapan canonical listing identity is ambiguous")
    total = payload.get("declaredTotal")
    rows = payload.get("rows")
    if (
        type(total) is not int or total < 1 or total > MAX_CARDS
        or payload.get("oldestFirst") is not True
        or not isinstance(rows, list) or len(rows) != total
        or payload.get("cardCount") != total
    ):
        raise DiscoveryIncompleteError("ebookjapan full-list total or oldest-first order is unverified")
    if payload.get("paginationCount") != 0 or payload.get("loadMoreCount") != 0:
        raise DiscoveryIncompleteError("ebookjapan listing has unsupported pagination or load-more controls")
    dom_paths = payload.get("domPaths")
    layout_paths = payload.get("layoutPaths")
    if not isinstance(dom_paths, list) or not isinstance(layout_paths, list) or dom_paths != layout_paths:
        raise DiscoveryIncompleteError("ebookjapan DOM order differs from its observed reading order")

    product_ids: list[str] = []
    all_records: list[DiscoveredRecord] = []
    owned_records: list[DiscoveredRecord] = []
    observed_volumes: list[int] = []
    for position, row in enumerate(rows, start=1):
        if not isinstance(row, Mapping):
            raise DiscoveryIncompleteError("ebookjapan card metadata is malformed")
        path = row.get("path")
        match = _PRODUCT_ID.fullmatch(path) if isinstance(path, str) else None
        if (
            match is None or match.group("series") != series_id
            or row.get("index") != position - 1
            or row.get("linkCount") != 1
            or not isinstance(row.get("title"), str) or not _normalized(row["title"])
        ):
            raise DiscoveryIncompleteError("ebookjapan card identity is missing or belongs to another series")
        external_id = match.group("product")
        product_ids.append(external_id)
        ownership = _classify_card(row)
        if ownership == "unknown":
            raise DiscoveryIncompleteError("ebookjapan card ownership is unknown or conflicting")

        order_key, order_label = _explicit_volume(row["title"])
        if order_key is not None:
            observed_volumes.append(int(order_key))
        record = DiscoveredRecord(
            item=DiscoveredItem(
                canonical_title=row["title"],
                kind="book",
                order_key=order_key,
                order_label=order_label,
            ),
            source=DiscoveredSource(
                external_id=external_id,
                url=f"{SITE_ORIGIN}{path}",
                access_mode="owned" if ownership == "owned" else "unknown",
                available=ownership == "owned",
                global_display_position=position,
            ),
        )
        all_records.append(record)
        if ownership == "owned":
            owned_records.append(record)

    if len(product_ids) != len(set(product_ids)):
        raise DiscoveryIncompleteError("ebookjapan listing contains duplicate product IDs")
    if observed_volumes != sorted(observed_volumes) or len(observed_volumes) != len(set(observed_volumes)):
        raise DiscoveryIncompleteError("ebookjapan explicit volume labels conflict with native order")
    if payload.get("domPaths") != [
        f"/books/{series_id}/{external_id}/" for external_id in product_ids
    ]:
        raise DiscoveryIncompleteError("ebookjapan card URLs changed or failed series binding")
    return all_records, owned_records


def _relevant_ebookjapan_host(url: str) -> bool:
    try:
        parsed = urlsplit(url)
    except ValueError:
        return False
    return (parsed.hostname or "").lower() == SITE_HOST


class EbookJapanDiscoveryAdapter(DiscoveryAdapter):
    """Enumerate only cards with a unique visible purchased badge."""

    registration_hosts = (SITE_HOST,)
    supports_bounded_discovery = False
    supports_incremental_discovery = False

    def resolve_registration_url(self, url: str) -> UrlResolution:
        series_id = parse_ebookjapan_series_url(url)
        if series_id is None:
            return UrlResolution(
                input_url=url,
                blockers=("ebookjapanは正規の全巻一覧URLを指定してください",),
            )
        return resolved_url(
            url,
            f"{SITE_ORIGIN}/books/all/{series_id}/",
            f"ebookjapan-series:{series_id}",
        )

    async def iter_records(
        self,
        page: Page,
        target: WatchlistTarget,
        mode: DiscoveryMode,
    ) -> AsyncIterator[DiscoveredRecord]:
        self.reset_complete_listing_inventory()
        series_id = parse_ebookjapan_series_url(target.url)
        if target.site != "ebookjapan" or series_id is None:
            raise DiscoveryIncompleteError("Watchlist target must use the exact ebookjapan full-list URL")
        if target.discovery_scope is not None:
            raise DiscoveryIncompleteError("ebookjapan Discovery does not support bounded scope")
        if mode != "full":
            raise DiscoveryIncompleteError("ebookjapan Discovery supports Full only")

        guard = AccessGuard.from_profile(
            site="ebookjapan",
            profile=AccessProfile(relevant_host=_relevant_ebookjapan_host),
            stop_on_http_403=True,
            stop_on_http_429=True,
            stop_on_challenge=True,
            stop_on_captcha=True,
        )
        guard.start(page)
        try:
            response = await page.goto(target.url, wait_until="domcontentloaded", timeout=WAIT_TIMEOUT_MS)
            await guard.check_page(page)
            if (
                response is None
                or response.status != 200
                or response.url != target.url
                or getattr(response.request, "redirected_from", None) is not None
                or page.url != target.url
            ):
                raise DiscoveryIncompleteError("ebookjapan full-list navigation was not an exact HTTP 200")
            content_type = response.headers.get("content-type", "").lower()
            if not content_type.startswith("text/html"):
                raise DiscoveryIncompleteError("ebookjapan source response is not an HTML document")
            charset_match = re.search(r"charset\s*=\s*['\"]?([a-z0-9._-]+)", content_type)
            encoding = charset_match.group(1) if charset_match else "utf-8"
            try:
                source_body = await response.body()
                if len(source_body) > MAX_SOURCE_RESPONSE_BYTES:
                    raise DiscoveryIncompleteError("ebookjapan source document exceeds its size bound")
                source_html = source_body.decode(encoding)
            except (UnicodeDecodeError, LookupError) as exc:
                raise DiscoveryIncompleteError("ebookjapan source document encoding is unsupported") from exc
            source_witness = parse_ebookjapan_source_witness(source_html, series_id=series_id)
            del source_body, source_html
            await guard.check_page(page)
            await page.wait_for_function(
                "() => document.querySelectorAll('.page-books-all__list-header').length === 1 "
                "&& document.querySelectorAll('.book-list__item').length > 0",
                timeout=WAIT_TIMEOUT_MS,
            )
            initial = await page.evaluate(_FULL_LISTING_JS)
            if not isinstance(initial, Mapping):
                raise DiscoveryIncompleteError("ebookjapan full-list header did not load")
            declared_total = initial.get("declaredTotal")
            if type(declared_total) is not int or not 1 <= declared_total <= MAX_CARDS:
                raise DiscoveryIncompleteError("ebookjapan native full-list total is missing or invalid")

            previous_signature: tuple[object, ...] | None = None
            stable_bottom_reads = 0
            elapsed_ms = 0
            payload: Mapping[str, Any] | None = None
            while elapsed_ms < SCROLL_TIMEOUT_MS:
                await page.evaluate(
                    "window.scrollTo({top: Math.max(document.body.scrollHeight, "
                    "document.documentElement.scrollHeight), behavior: 'instant'})"
                )
                await page.wait_for_timeout(SCROLL_POLL_MS)
                await guard.check_page(page)
                observed = await page.evaluate(_FULL_LISTING_JS)
                if not isinstance(observed, Mapping) or not isinstance(observed.get("domPaths"), list):
                    raise DiscoveryIncompleteError("ebookjapan bottom-list snapshot is unavailable")
                paths = observed.get("domPaths")
                if len(paths) > declared_total:
                    raise DiscoveryIncompleteError("ebookjapan listing exceeds its native total")
                signature = _rights_signature(observed)
                rights_match = _source_rights_match(observed, source_witness)
                if (
                    observed.get("bottomReached") is True
                    and signature == previous_signature
                    and observed.get("accountAuthenticated") is True
                    and rights_match
                ):
                    stable_bottom_reads += 1
                elif (
                    observed.get("bottomReached") is True
                    and observed.get("accountAuthenticated") is True
                    and rights_match
                ):
                    stable_bottom_reads = 1
                else:
                    stable_bottom_reads = 0
                previous_signature = signature
                payload = observed
                if (
                    stable_bottom_reads >= STABLE_BOTTOM_READS
                    and len(paths) == declared_total
                    and observed.get("accountAuthenticated") is True
                    and rights_match
                ):
                    break
                elapsed_ms += SCROLL_POLL_MS
            else:
                raise DiscoveryIncompleteError("ebookjapan full listing did not exhaust and stabilize")

            final_payload = await page.evaluate(_FULL_LISTING_JS)
            await guard.check_page(page)
            if (
                not isinstance(payload, Mapping)
                or not isinstance(final_payload, Mapping)
                or _rights_signature(final_payload) != _rights_signature(payload)
                or final_payload.get("bottomReached") is not True
                or len(final_payload.get("rows", ())) != declared_total
                or page.url != target.url
                or not _source_rights_match(final_payload, source_witness)
            ):
                raise DiscoveryIncompleteError("ebookjapan listing changed after bottom stabilization")
            payload = final_payload
            all_records, owned_records = parse_ebookjapan_listing(payload, series_id=series_id)
            before_emission = await page.evaluate(_FULL_LISTING_JS)
            if (
                not isinstance(before_emission, Mapping)
                or _rights_signature(before_emission) != _rights_signature(payload)
                or before_emission.get("bottomReached") is not True
                or not _source_rights_match(before_emission, source_witness)
            ):
                raise DiscoveryIncompleteError("ebookjapan listing changed before record emission")
            await guard.check_page(page)
        except DiscoveryIncompleteError:
            raise
        except PlaywrightError as exc:
            raise DiscoveryIncompleteError("ebookjapan full listing did not load or stabilize") from exc
        except TimeoutError as exc:
            raise DiscoveryIncompleteError("ebookjapan full listing timed out") from exc
        finally:
            await guard.close()

        self.capture_complete_listing_inventory(
            target=target,
            all_records=all_records,
            selected_records=owned_records,
            listing_identity=f"ebookjapan-series:{series_id}",
        )
        # The native full list is oldest-first; the service's canonical full
        # stream is newest-first. Global display positions retain the observed
        # oldest-first authority independently of yield order.
        for record in reversed(owned_records):
            yield record
