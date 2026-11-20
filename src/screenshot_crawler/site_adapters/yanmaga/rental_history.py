"""Narrow parser for the observed Yanmaga rental-history countdown card."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING
from urllib.parse import parse_qsl, quote, urlsplit

from playwright.async_api import Error as PlaywrightError
from playwright.async_api import Page
from playwright.async_api import TimeoutError as PlaywrightTimeoutError

if TYPE_CHECKING:
    from screenshot_crawler.site_adapters.yanmaga.discovery import YanmagaEpisodeParts

_LABEL_CLASSES = frozenset(
    {
        "tw:flex",
        "tw:items-center",
        "tw:justify-center",
        "tw:px-1.75",
        "tw:py-9xs",
        "tw:border",
        "tw:box-border",
        "tw:border-gray-gallery",
        "tw:w-17.5",
        "tw:h-4",
        "tw:text-body-4xs-b",
        "tw:xl:w-19",
        "tw:xl:h-4.5",
        "tw:xl:text-body-3xs-bold",
    }
)
_VALUE_CLASSES = frozenset(
    {
        "tw:flex",
        "tw:items-center",
        "tw:justify-center",
        "tw:px-6xs",
        "tw:py-9xs",
        "tw:text-center",
        "tw:text-nowrap",
        "tw:bg-red-crimson",
        "tw:text-white",
        "tw:w-16",
        "tw:h-4",
        "tw:text-body-4xs-b",
        "tw:xl:w-18",
        "tw:xl:h-4.5",
        "tw:xl:text-body-3xs-bold",
    }
)
_EXPIRED_VALUE_CLASSES = (_VALUE_CLASSES - {"tw:bg-red-crimson", "tw:text-white"}) | {
    "tw:bg-gray-gallery", "tw:text-black",
}
_PAIR_PARENT_CLASSES = frozenset(
    {"tw:flex", "tw:items-center", "tw:justify-center", "tw:w-fit"}
)
_ANCESTOR_CLASSES = (
    frozenset(
        {
            "tw:flex",
            "tw:justify-between",
            "tw:items-center",
            "tw:gap-7xs",
            "tw:h-4",
            "tw:xl:h-4.5",
        }
    ),
    frozenset(
        {
            "tw:relative",
            "tw:flex",
            "tw:flex-col",
            "tw:gap-y-8xs",
            "tw:xl:gap-y-7xs",
        }
    ),
    frozenset(
        {
            "tw:flex",
            "tw:flex-col",
            "tw:flex-1",
            "tw:min-w-0",
            "tw:w-full",
            "tw:gap-7xs",
            "tw:xl:gap-5xs",
        }
    ),
    frozenset(
        {
            "tw:flex",
            "tw:bg-white",
            "tw:relative",
            "tw:border-b",
            "tw:hover:opacity-50",
            "tw:has-[button:hover]:opacity-100",
            "tw:gap-6xs",
            "tw:px-6xs",
            "tw:py-7xs",
            "tw:w-full",
            "tw:border-gray-mercury",
            "tw:xl:flex-col",
            "tw:xl:gap-5xs",
            "tw:xl:p-8xs",
            "tw:xl:w-[238px]",
            "tw:xl:border-transparent",
        }
    ),
)
_ANCHOR_CLASSES = frozenset({"tw:no-underline", "tw:text-inherit"})
_HISTORY_LINK_CLASSES = frozenset(
    {
        "tw:text-button-sm",
        "tw:text-center",
        "tw:h-8",
        "tw:text-gray-dusty-dark",
        "tw:pb-[11px]",
    }
)
_RENTAL_COLLECTION_CLASSES = frozenset(
    {
        "tw:grid",
        "tw:grid-cols-1",
        "tw:xl:grid-cols-4",
        "tw:xl:gap-4xs",
        "tw:md:py-xs",
    }
)
_HISTORY_MORE_CLASSES = frozenset({"tw:flex", "tw:justify-center", "tw:pt-4xs"})
_HISTORY_MORE_BUTTON_CLASSES = frozenset({
    "tw:rounded-full", "tw:inline-flex", "tw:items-center", "tw:justify-center",
    "tw:border", "tw:hover:opacity-60", "tw:disabled:opacity-40",
    "tw:disabled:pointer-events-none", "tw:border-black", "tw:text-black",
    "tw:pl-2xs", "tw:pr-4xs", "tw:gap-9xs", "tw:text-button-xs", "tw:w-[162px]",
})
_HIDE_CLASS = r"(?:^|[-_:])(?:hidden|hide|invisible|sr-only)(?:$|[-_:])"
_MAX_HISTORY_BYTES = 4 * 1024 * 1024
_MAX_HISTORY_PAGES = 50
_MAX_HISTORY_ROWS = 1_000
_HISTORY_PAGE_SIZE = 20
_MAX_COUNTDOWN_HOURS = 23
MAX_WAIT_RENTAL_COUNTDOWN_HOURS = 72
_MAX_DATE_SKEW_SECONDS = 5


@dataclass(frozen=True, slots=True)
class RentalCountdown:
    """Exact target's native remaining-time field and safe lower bound."""

    observed_at: datetime
    remaining_hours: int
    access_granted_until: datetime | None
    expiry_evidence: str | None
    remaining_days: int | None = None

    @property
    def active(self) -> bool:
        return self.remaining_hours > 0 or (self.remaining_days or 0) > 0


@dataclass(frozen=True, slots=True)
class RentalHistoryObservation:
    """Active countdown, or no active rental proved by absence/explicit expiry."""

    external_id: str
    countdown: RentalCountdown | None


def rental_history_target_url(target: YanmagaEpisodeParts) -> str:
    return (
        "https://yanmaga.jp/comics/"
        f"{quote(target.slug, safe='')}/{target.episode_id}"
    )


def rental_history_snapshot_js() -> str:
    """Return a detached-DOM parser bound to one exact public episode anchor."""

    return r"""(args) => {
      const parsed = new DOMParser().parseFromString(args.html, 'text/html');
      const target = new URL(args.targetUrl);
      const labelClasses = new Set(args.labelClasses);
      const valueClasses = new Set(args.valueClasses);
      const expiredValueClasses = new Set(args.expiredValueClasses);
      const parentClasses = new Set(args.parentClasses);
      const anchorClasses = new Set(args.anchorClasses);
      const ancestorClasses = args.ancestorClasses.map(value => new Set(value));
      const collectionClasses = args.collectionClasses
        ? new Set(args.collectionClasses) : null;
      const sameSet = (actual, expected) => actual.length === expected.size &&
        actual.every(value => expected.has(value));
      const collections = collectionClasses
        ? [...parsed.querySelectorAll('ul')].filter(node =>
            node.id === 'content_card_list' &&
            sameSet([...node.classList], collectionClasses)) : [];
      const collection = collections.length === 1 ? collections[0] : null;
      const collectionRows = collection ? [...collection.children] : [];
      const indices = collectionRows.map(row => row.getAttribute('data-index'));
      const cardsValid = collectionRows.every(row => {
        if (row.tagName !== 'LI' || row.classList.length !== 0 ||
            row.getAttributeNames().length !== 1 ||
            row.getAttributeNames()[0] !== 'data-index' ||
            !/^\d+$/.test(row.getAttribute('data-index') || '')) return false;
        const anchors = [...row.querySelectorAll('a[href]')];
        if (anchors.length !== 1 || !sameSet([...anchors[0].classList], anchorClasses))
          return false;
        try {
          const href = new URL(anchors[0].getAttribute('href'), target.origin);
          return href.origin === target.origin &&
            /^\/comics\/[^/]+\/[0-9a-f]{32}$/.test(href.pathname) &&
            !href.username && !href.password && !href.search && !href.hash;
        } catch { return false; }
      });
      const pagingScope = collection?.parentElement || collection;
      const pagination = pagingScope ? [...pagingScope.querySelectorAll(
        'button,a[rel="next"],[data-next],[class*="pagination" i],'
        + '[class*="infinite" i],[data-infinite-scroll],[data-load-more]')] : [];
      const collectionValid = !!collection &&
        [...new Set(indices)].length === indices.length && cardsValid &&
        collection.getAttributeNames().length === 2 &&
        collection.getAttributeNames().includes('class') &&
        collection.getAttributeNames().includes('id') &&
        collection.id === 'content_card_list' && pagination.length === 0;
      const exactTargetAnchors = [...parsed.querySelectorAll('a[href]')].filter(anchor => {
        try {
          const url = new URL(anchor.getAttribute('href'), target.origin);
          return url.origin === target.origin && url.pathname === target.pathname &&
            !url.username && !url.password && !url.search && !url.hash;
        } catch { return false; }
      });
      const targetAnchors = collectionClasses
        ? exactTargetAnchors.filter(anchor => collectionValid && anchor.closest('ul') === collection)
        : exactTargetAnchors;
      const unsafeHidden = node => {
        for (let current = node; current; current = current.parentElement) {
          const style = current.style;
          const hiddenStyle = style.display === 'none' ||
            style.visibility === 'hidden' || style.visibility === 'collapse' ||
            (style.opacity !== '' && Number(style.opacity) === 0);
          if (current.hasAttribute('hidden') ||
              (current.getAttribute('aria-hidden') || '').toLowerCase() === 'true' ||
              hiddenStyle || [...current.classList].some(token => new RegExp(args.hideClass).test(token)))
            return true;
        }
        return false;
      };
      const cards = targetAnchors.map(anchor => {
        const leaves = [...anchor.querySelectorAll('div')].filter(node => node.children.length === 0);
        const labels = leaves.filter(node => sameSet([...node.classList], labelClasses) &&
          (node.textContent || '').trim() === args.label);
        const values = leaves.filter(node => sameSet([...node.classList], valueClasses) &&
          (/^\s*\u6b8b\u308a\s*[0-9]+\s*\u6642\u9593\s*$/.test(node.textContent || '') ||
           (args.allowDays && /^\s*\u6b8b\u308a\s*[0-9]+\s*\u65e5\s*$/.test(node.textContent || ''))));
        const expiredValues = leaves.filter(node =>
          sameSet([...node.classList], expiredValueClasses) &&
          (node.textContent || '').trim() === '\u671f\u9650\u5207\u308c');
        values.push(...expiredValues);
        const pairs = [];
        for (const label of labels) for (const value of values) {
          const parent = label.parentElement;
          if (parent && parent === value.parentElement && parent.tagName === 'DIV' &&
              sameSet([...parent.classList], parentClasses) && parent.children.length === 2 &&
              parent.children[0] === label && parent.children[1] === value) {
            let path = parent;
            let pathValid = true;
            for (const expected of ancestorClasses) {
              path = path.parentElement;
              if (!path || path.tagName !== 'DIV' || !sameSet([...path.classList], expected)) {
                pathValid = false;
                break;
              }
            }
            path = path?.parentElement;
            pathValid = pathValid && path === anchor && path.tagName === 'A' &&
              sameSet([...path.classList], anchorClasses);
            if (!pathValid) continue;
            const hoursMatch = /^\s*\u6b8b\u308a\s*([0-9]+)\s*\u6642\u9593\s*$/.exec(value.textContent || '');
            const daysMatch = args.allowDays
              ? /^\s*\u6b8b\u308a\s*([0-9]+)\s*\u65e5\s*$/.exec(value.textContent || '') : null;
            pairs.push({label, value, parent,
              expired: expiredValues.includes(value),
              hours: hoursMatch ? Number(hoursMatch[1]) : null,
              days: daysMatch ? Number(daysMatch[1]) : null});
          }
        }
        const hours = pairs.length === 1 ? pairs[0].hours : null;
        const days = pairs.length === 1 ? pairs[0].days : null;
        const hoursValid = Number.isSafeInteger(hours) && hours > 0 && hours <= args.maxHours;
        const daysValid = args.allowDays && Number.isSafeInteger(days) && days > 0 &&
          days * 24 <= args.maxHours;
        const valid = pairs.length === 1 && !unsafeHidden(anchor) &&
          !unsafeHidden(pairs[0].label) && !unsafeHidden(pairs[0].value) &&
          hoursValid !== daysValid;
        return {
          labelCount: labels.length,
          valueCount: values.length,
          pairCount: pairs.length,
          hidden: targetAnchors.length !== 1 || (pairs.length === 1 &&
            (unsafeHidden(anchor) || unsafeHidden(pairs[0].label) || unsafeHidden(pairs[0].value))),
          expired: pairs.length === 1 && pairs[0].expired && !unsafeHidden(anchor) &&
            !unsafeHidden(pairs[0].label) && !unsafeHidden(pairs[0].value),
          hours: valid && hoursValid ? hours : null,
          days: valid && daysValid ? days : null
        };
      });
      return {
        targetAnchorCount: exactTargetAnchors.length,
        targetInCollectionCount: targetAnchors.length,
        cards,
        collectionValid: collectionClasses ? collectionValid : null
      };
    }"""


async def parse_rental_history_html(
    page: Page,
    html: str,
    *,
    target: YanmagaEpisodeParts,
    observed_at: datetime,
    max_countdown_hours: int = _MAX_COUNTDOWN_HOURS,
) -> RentalCountdown | None:
    """Parse one exact native card; ambiguous, hidden, or malformed data is unknown."""

    if (
        observed_at.tzinfo is None
        or observed_at.utcoffset() is None
        or isinstance(max_countdown_hours, bool)
        or not isinstance(max_countdown_hours, int)
        or not 1 <= max_countdown_hours <= MAX_WAIT_RENTAL_COUNTDOWN_HOURS
    ):
        return None
    if not isinstance(html, str) or not html:
        return None
    try:
        raw = await page.evaluate(
            rental_history_snapshot_js(),
            {
                "html": html,
                "targetUrl": rental_history_target_url(target),
                "label": "\u30ec\u30f3\u30bf\u30eb\u671f\u9593",
                "labelClasses": sorted(_LABEL_CLASSES),
                "valueClasses": sorted(_VALUE_CLASSES),
                "expiredValueClasses": sorted(_EXPIRED_VALUE_CLASSES),
                "parentClasses": sorted(_PAIR_PARENT_CLASSES),
                "ancestorClasses": [sorted(classes) for classes in _ANCESTOR_CLASSES],
                "anchorClasses": sorted(_ANCHOR_CLASSES),
                "hideClass": _HIDE_CLASS,
                "maxHours": max_countdown_hours,
                "allowDays": max_countdown_hours > _MAX_COUNTDOWN_HOURS,
            },
        )
    except (PlaywrightError, PlaywrightTimeoutError, TypeError, ValueError):
        return None
    if not isinstance(raw, dict) or raw.get("targetAnchorCount") != 1:
        return None
    cards = raw.get("cards")
    if not isinstance(cards, list) or len(cards) != 1 or not isinstance(cards[0], dict):
        return None
    card = cards[0]
    hours = card.get("hours")
    days = card.get("days")
    valid_hours = (
        not isinstance(hours, bool)
        and isinstance(hours, int)
        and 1 <= hours <= max_countdown_hours
    )
    valid_days = (
        max_countdown_hours > _MAX_COUNTDOWN_HOURS
        and not isinstance(days, bool)
        and isinstance(days, int)
        and days > 0
        and days * 24 <= max_countdown_hours
    )
    if (
        card.get("labelCount") != 1
        or card.get("valueCount") != 1
        or card.get("pairCount") != 1
        or card.get("hidden") is not False
        or valid_hours == valid_days
    ):
        return None
    return RentalCountdown(
        observed_at=observed_at.astimezone(UTC),
        remaining_hours=hours if valid_hours else 0,
        # A parsed card alone has no response-freshness proof. Only the bounded
        # runtime fetch below may derive a finite grant observation/estimate.
        access_granted_until=None,
        expiry_evidence=None,
        remaining_days=days if valid_days else None,
    )


async def _fetch_rental_history_observations(
    page: Page,
    *,
    observed_mypage_href: str,
    targets: tuple[YanmagaEpisodeParts, ...],
    require_complete_collection: bool,
    max_countdown_hours: int,
) -> tuple[RentalHistoryObservation, ...] | None:
    """Observe active vs proved-inactive history without executing page content."""

    if (
        isinstance(max_countdown_hours, bool)
        or not isinstance(max_countdown_hours, int)
        or not 1 <= max_countdown_hours <= MAX_WAIT_RENTAL_COUNTDOWN_HOURS
    ):
        return None
    try:
        current = urlsplit(page.url)
        mypage = urlsplit(observed_mypage_href)
        port = mypage.port
        current_query = parse_qsl(current.query, keep_blank_values=True)
    except ValueError:
        return None
    expected_work_path = f"/comics/{quote(targets[0].slug, safe='')}" if targets else ""
    expected_viewer_paths = {
        f"/viewer/comics/{quote(target.slug, safe='')}/{target.episode_id}"
        for target in targets
    }
    current_document_ok = (
        current.path == expected_work_path
        and current_query in ([], [("sort", "older")])
    ) or (
        current.path in expected_viewer_paths
        and (
            not current.query
            or (len(current_query) == 1 and re.fullmatch(r"cid=[A-Za-z0-9]{20}", current.query))
        )
    )
    if (
        current.scheme.lower() != "https"
        or (current.hostname or "").lower() != "yanmaga.jp"
        or not current_document_ok
        or current.username is not None
        or current.password is not None
        or current.fragment
        or mypage.scheme.lower() != "https"
        or (mypage.hostname or "").lower() != "yanmaga.jp"
        or port not in (None, 443)
        or mypage.username is not None
        or mypage.password is not None
        or mypage.path != "/mypage"
        or mypage.query
        or mypage.fragment
        or not targets
        or len({target.episode_id for target in targets}) != len(targets)
        or len({target.slug for target in targets}) != 1
    ):
        return None
    observed_at = datetime.now(UTC)
    target_args = [
        {
            "externalId": f"{target.slug}:{target.episode_id}",
            "targetUrl": rental_history_target_url(target),
        }
        for target in targets
    ]
    parser = rental_history_snapshot_js()
    fetch_script = rf"""async (args) => {{
      const origin = location.origin;
      const safeUrl = (value, path) => {{
        try {{
          const url = new URL(value, origin);
          return url.origin === origin && url.pathname === path &&
            !url.username && !url.password && !url.hash ? url : null;
        }} catch {{ return null; }}
      }};
      let totalBytes = 0;
      const readDocument = async (href, stream = false) => {{
        const requested = new URL(href);
        const expectedPath = stream ? '/api/mypage/rentals' : '/mypage';
        const expectedType = stream ? 'text/vnd.turbo-stream.html' : 'text/html';
        if (requested.origin !== origin || requested.pathname !== expectedPath) return null;
        const requestStartedAt = Date.now();
        const response = await fetch(href, {{method:'GET',cache:'no-store',redirect:'error',
          credentials:'same-origin',signal:AbortSignal.timeout(15000)}});
        const type = (response.headers.get('content-type') || '').toLowerCase();
        const mimeType = type.split(';', 1)[0].trim();
        const age = response.headers.get('age');
        const cacheControl = (response.headers.get('cache-control') || '')
          .toLowerCase().split(',').map(value => value.trim());
        const dateText = response.headers.get('date') || '';
        const date = Date.parse(dateText);
        const standardDate = Number.isFinite(date) && new Date(date).toUTCString() === dateText;
        const cacheControlExact = cacheControl.length === 3 && new Set(cacheControl).size === 3 &&
          cacheControl.includes('private') && cacheControl.includes('max-age=0') &&
          cacheControl.includes('must-revalidate');
        if (response.status !== 200 || response.url !== href ||
            mimeType !== expectedType || response.redirected || !response.body ||
            age !== null || !standardDate ||
            Math.abs(date - requestStartedAt) > args.maxDateSkewMs ||
            !cacheControlExact)
          return null;
        const chunks = [];
        let size = 0;
        const reader = response.body.getReader();
        while (true) {{
          const part = await reader.read();
          if (part.done) break;
          size += part.value.byteLength;
          totalBytes += part.value.byteLength;
          if (totalBytes > args.maxBytes) {{ await reader.cancel(); return null; }}
          chunks.push(part.value);
        }}
        const joined = new Uint8Array(size);
        let offset = 0;
        for (const chunk of chunks) {{ joined.set(chunk, offset); offset += chunk.length; }}
        return new TextDecoder('utf-8').decode(joined);
      }};
      const mypageHref = safeUrl(args.mypageHref, '/mypage');
      if (!mypageHref || mypageHref.search || origin !== 'https://yanmaga.jp') return {{ok:false}};
      const mypageHtml = await readDocument(mypageHref.href);
      if (!mypageHtml) return {{ok:false}};
      const mypageDoc = new DOMParser().parseFromString(mypageHtml, 'text/html');
      const rental = '\u30ec\u30f3\u30bf\u30eb', history = '\u5c65\u6b74';
      const historyClasses = new Set(args.historyLinkClasses);
      const sameSet = (actual, expected) => actual.length === expected.size &&
        actual.every(value => expected.has(value));
      const hidden = element => {{
        for (let node = element; node; node = node.parentElement) {{
          const style = node.style;
          if (node.hasAttribute('hidden') ||
              (node.getAttribute('aria-hidden') || '').toLowerCase() === 'true' ||
              style.display === 'none' || style.visibility === 'hidden' ||
              style.visibility === 'collapse' ||
              (style.opacity !== '' && Number(style.opacity) === 0) ||
              [...node.classList].some(token => new RegExp(args.hideClass).test(token))) return true;
        }}
        return false;
      }};
      const links = [];
      for (const anchor of mypageDoc.querySelectorAll('a[href]')) {{
        const label = (anchor.textContent || anchor.getAttribute('aria-label') || '')
          .replace(/\s+/g, ' ').trim();
        let url;
        try {{ url = new URL(anchor.getAttribute('href'), args.mypageHref); }} catch {{ continue; }}
        const params = [...url.searchParams.entries()];
        const keys = [...new Set(params.map(([key]) => key))];
        if (anchor.tagName === 'A' && sameSet([...anchor.classList], historyClasses) &&
            !hidden(anchor) && url.origin === origin && url.pathname === '/mypage' &&
            !url.username && !url.password && !url.hash && params.length === 1 &&
            keys.length === 1 && keys[0] === 'tab' && params[0][1] !== '' &&
            label === rental + history && anchor.getAttribute('target') === null) links.push(url.href);
      }}
      const uniqueLinks = [...new Set(links)];
      if (links.length !== 1 || uniqueLinks.length !== 1) return {{ok:false}};
      const historyHref = safeUrl(uniqueLinks[0], '/mypage');
      if (!historyHref) return {{ok:false}};
      let historyHtml = await readDocument(historyHref.href);
      if (!historyHtml) return {{ok:false}};
      const doc = new DOMParser().parseFromString(historyHtml, 'text/html');
      if (args.requireCompleteCollection || doc.querySelector('#content_more_button')) {{
        // Expand only the observed native GET/Turbo shape, entirely in detached
        // DOM. No script execution, live DOM replacement or episode entry.
        const exactAttrs = (node, names) => node &&
          sameSet(node.getAttributeNames(), new Set(names));
        const exactClasses = (node, names) => node &&
          sameSet([...node.classList], new Set(names));
        const collections = [...doc.querySelectorAll('#content_card_list')];
        if (collections.length !== 1) return {{ok:false}};
        const collection = collections[0];
        if (collection.tagName !== 'UL' || !exactAttrs(collection, ['id','class']) ||
            !exactClasses(collection, args.collectionClasses)) return {{ok:false}};
        const validRows = () => {{
          const rows = [...collection.children];
          const hrefs = [];
          if (rows.length > args.maxRows) return false;
          for (const [index, row] of rows.entries()) {{
            if (row.tagName !== 'LI' || !exactAttrs(row, ['data-index']) ||
                row.getAttribute('data-index') !== String(index)) return false;
            const anchors = row.querySelectorAll('a[href]');
            if (anchors.length !== 1) return false;
            let url;
            try {{ url = new URL(anchors[0].getAttribute('href'), origin); }} catch {{ return false; }}
            if (url.origin !== origin || !/^\/comics\/[^/]+\/[0-9a-f]{{32}}$/.test(url.pathname) ||
                url.username || url.password || url.search || url.hash) return false;
            hrefs.push(url.href);
          }}
          return new Set(hrefs).size === hrefs.length;
        }};
        for (let pageIndex = 0; ; pageIndex++) {{
          if (!validRows()) return {{ok:false}};
          const controls = [...doc.querySelectorAll('#content_more_button')];
          if (controls.length === 0) break;
          if (controls.length !== 1 || pageIndex >= args.maxPages) return {{ok:false}};
          const more = controls[0];
          const anchor = more.firstElementChild;
          const button = anchor?.firstElementChild;
          if (more.tagName !== 'DIV' || more.parentElement !== collection.parentElement ||
              !exactAttrs(more, ['id','class']) || !exactClasses(more, args.moreClasses) ||
              hidden(more) || more.children.length !== 1 || anchor?.tagName !== 'A' ||
              !exactAttrs(anchor, ['href','data-turbo','data-turbo-stream']) ||
              anchor.getAttribute('data-turbo') !== 'true' ||
              anchor.getAttribute('data-turbo-stream') !== 'true' ||
              anchor.children.length !== 1 || button?.tagName !== 'BUTTON' ||
              !exactAttrs(button, ['class']) || !exactClasses(button, args.moreButtonClasses) ||
              hidden(button) ||
              button.textContent.trim() !== '\u3082\u3063\u3068\u898b\u308b') return {{ok:false}};
          const offset = collection.children.length;
          const nextHref = safeUrl(anchor.getAttribute('href'), '/api/mypage/rentals');
          if (!nextHref || offset === 0 || offset >= args.maxRows ||
              nextHref.search !== '?offset=' + offset) return {{ok:false}};
          const streamHtml = await readDocument(nextHref.href, true);
          if (!streamHtml) return {{ok:false}};
          const streamDoc = new DOMParser().parseFromString(streamHtml, 'text/html');
          const streams = [...streamDoc.body.children];
          if (streams.length !== 2 || streamDoc.querySelectorAll('turbo-stream').length !== 2)
            return {{ok:false}};
          for (const [index, stream] of streams.entries()) {{
            if (stream.tagName !== 'TURBO-STREAM' || !exactAttrs(stream, ['action','target']) ||
                stream.getAttribute('action') !== (index === 0 ? 'append' : 'replace') ||
                stream.getAttribute('target') !== (index === 0 ? 'content_card_list' : 'content_more_button') ||
                stream.children.length !== 1 || stream.firstElementChild.tagName !== 'TEMPLATE' ||
                stream.firstElementChild.attributes.length !== 0) return {{ok:false}};
          }}
          const added = [...streams[0].firstElementChild.content.children];
          const replacement = streams[1].firstElementChild.content;
          if (added.length === 0 || added.length > args.pageSize ||
              replacement.children.length > 1 ||
              (replacement.children.length === 1 &&
               (replacement.firstElementChild.tagName !== 'DIV' ||
                replacement.firstElementChild.id !== 'content_more_button')) ||
              (replacement.children.length === 0 && replacement.textContent.trim() !== ''))
            return {{ok:false}};
          for (const row of added) collection.appendChild(doc.importNode(row, true));
          more.replaceWith(doc.importNode(replacement, true));
        }}
        historyHtml = doc.documentElement.outerHTML;
      }}
      const parse = {parser};
      const proofs = [];
      const observations = [];
      for (const target of args.targets) {{
        const snapshot = parse({{html:historyHtml,targetUrl:target.targetUrl,
          label:args.label,labelClasses:args.labelClasses,valueClasses:args.valueClasses,
          expiredValueClasses:args.expiredValueClasses,
          parentClasses:args.parentClasses,ancestorClasses:args.ancestorClasses,
          anchorClasses:args.anchorClasses,hideClass:args.hideClass,
          maxHours:args.maxHours,allowDays:args.allowDays,
          collectionClasses:args.requireCompleteCollection ? args.collectionClasses : null}});
        if (args.requireCompleteCollection && snapshot.collectionValid !== true)
          return {{ok:false}};
        if (snapshot.targetAnchorCount === 0) {{
          observations.push({{externalId:target.externalId,status:'absent'}});
          continue;
        }}
        if (snapshot.targetAnchorCount !== 1 ||
            snapshot.targetInCollectionCount !== 1 || !Array.isArray(snapshot.cards) ||
            snapshot.cards.length !== 1) return {{ok:false}};
        const card = snapshot.cards[0];
        const hoursValid = Number.isSafeInteger(card.hours) && card.hours > 0 &&
          card.hours <= args.maxHours;
        const daysValid = args.allowDays && Number.isSafeInteger(card.days) && card.days > 0 &&
          card.days * 24 <= args.maxHours;
        if (card.labelCount === 1 && card.valueCount === 1 && card.pairCount === 1 &&
            card.hidden === false && card.expired === true && !hoursValid && !daysValid) {{
          observations.push({{externalId:target.externalId,status:'expired'}});
        }} else if (card.labelCount === 1 && card.valueCount === 1 && card.pairCount === 1 &&
            card.hidden === false && hoursValid !== daysValid) {{
          const hours = hoursValid ? card.hours : null;
          const days = daysValid ? card.days : null;
          proofs.push({{externalId:target.externalId,hours,days}});
          observations.push({{externalId:target.externalId,status:'active',hours,days}});
        }} else return {{ok:false}};
      }}
      return {{ok:true,proofs,observations}};
    }}"""
    try:
        raw = await page.evaluate(
            fetch_script,
            {
                "mypageHref": observed_mypage_href,
                "targets": target_args,
                "requireCompleteCollection": require_complete_collection,
                "collectionClasses": sorted(_RENTAL_COLLECTION_CLASSES),
                "maxBytes": _MAX_HISTORY_BYTES,
                "maxPages": _MAX_HISTORY_PAGES,
                "maxRows": _MAX_HISTORY_ROWS,
                "pageSize": _HISTORY_PAGE_SIZE,
                "moreClasses": sorted(_HISTORY_MORE_CLASSES),
                "moreButtonClasses": sorted(_HISTORY_MORE_BUTTON_CLASSES),
                "maxHours": max_countdown_hours,
                "allowDays": max_countdown_hours > _MAX_COUNTDOWN_HOURS,
                "maxDateSkewMs": _MAX_DATE_SKEW_SECONDS * 1000,
                "label": "\u30ec\u30f3\u30bf\u30eb\u671f\u9593",
                "labelClasses": sorted(_LABEL_CLASSES),
                "valueClasses": sorted(_VALUE_CLASSES),
                "expiredValueClasses": sorted(_EXPIRED_VALUE_CLASSES),
                "parentClasses": sorted(_PAIR_PARENT_CLASSES),
                "ancestorClasses": [sorted(classes) for classes in _ANCESTOR_CLASSES],
                "anchorClasses": sorted(_ANCHOR_CLASSES),
                "hideClass": _HIDE_CLASS,
                "historyLinkClasses": sorted(_HISTORY_LINK_CLASSES),
            },
        )
    except (PlaywrightError, PlaywrightTimeoutError, TypeError, ValueError):
        return None
    if (
        not isinstance(raw, dict)
        or raw.get("ok") is not True
        or not isinstance(raw.get("observations"), list)
        or len(raw["observations"]) != len(targets)
    ):
        return None
    observations: list[RentalHistoryObservation] = []
    seen: set[str] = set()
    for entry in raw["observations"]:
        if not isinstance(entry, dict):
            return None
        external_id = entry.get("externalId")
        status = entry.get("status")
        hours = entry.get("hours")
        days = entry.get("days")
        if not isinstance(external_id, str) or external_id in seen:
            return None
        seen.add(external_id)
        if status in {"absent", "expired"}:
            observations.append(RentalHistoryObservation(external_id, None))
            continue
        valid_hours = (
            not isinstance(hours, bool)
            and isinstance(hours, int)
            and 1 <= hours <= max_countdown_hours
        )
        valid_days = (
            max_countdown_hours > _MAX_COUNTDOWN_HOURS
            and not isinstance(days, bool)
            and isinstance(days, int)
            and days > 0
            and days * 24 <= max_countdown_hours
        )
        if status != "active" or valid_hours == valid_days:
            return None
        if valid_hours:
            grant_until = (
                observed_at
                - timedelta(seconds=_MAX_DATE_SKEW_SECONDS)
                + timedelta(hours=hours - 1)
                if hours > 1
                else None
            )
            remaining_hours = hours
            remaining_days = None
            expiry_evidence = "site_countdown_lower_bound"
        else:
            # Day-only text does not expose its exact rounding or deadline.
            # Store an eligibility estimate with a one-hour margin; the Adapter
            # must still reconfirm the exact active rental before Source entry.
            grant_until = (
                observed_at
                - timedelta(seconds=_MAX_DATE_SKEW_SECONDS)
                + timedelta(days=days)
                - timedelta(hours=1)
            )
            remaining_hours = 0
            remaining_days = days
            expiry_evidence = "site_day_countdown_estimate"
        observations.append(
            RentalHistoryObservation(
                external_id,
                RentalCountdown(
                    observed_at=observed_at,
                    remaining_hours=remaining_hours,
                    access_granted_until=grant_until,
                    expiry_evidence=expiry_evidence if grant_until is not None else None,
                    remaining_days=remaining_days,
                ),
            )
        )
    expected_ids = {f"{target.slug}:{target.episode_id}" for target in targets}
    if seen != expected_ids:
        return None
    return tuple(observations)


async def fetch_rental_history_observations(
    page: Page,
    *,
    observed_mypage_href: str,
    targets: tuple[YanmagaEpisodeParts, ...],
    max_countdown_hours: int = _MAX_COUNTDOWN_HOURS,
) -> tuple[RentalHistoryObservation, ...] | None:
    """Return active or verified-inactive targets, or ``None`` when unknown."""

    return await _fetch_rental_history_observations(
        page,
        observed_mypage_href=observed_mypage_href,
        targets=targets,
        require_complete_collection=True,
        max_countdown_hours=max_countdown_hours,
    )


async def fetch_rental_history_countdowns(
    page: Page,
    *,
    observed_mypage_href: str,
    targets: tuple[YanmagaEpisodeParts, ...],
    max_countdown_hours: int = _MAX_COUNTDOWN_HOURS,
) -> tuple[tuple[str, RentalCountdown], ...]:
    """Return positive grants, including targets behind bounded native More pages."""

    observations = await _fetch_rental_history_observations(
        page,
        observed_mypage_href=observed_mypage_href,
        targets=targets,
        require_complete_collection=False,
        max_countdown_hours=max_countdown_hours,
    )
    if observations is None:
        return ()
    return tuple(
        (observation.external_id, observation.countdown)
        for observation in observations
        if observation.countdown is not None
    )



