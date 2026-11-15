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
_HIDE_CLASS = r"(?:^|[-_:])(?:hidden|hide|invisible|sr-only)(?:$|[-_:])"
_MAX_HISTORY_BYTES = 4 * 1024 * 1024
_MAX_COUNTDOWN_HOURS = 23
_MAX_DATE_SKEW_SECONDS = 5


@dataclass(frozen=True, slots=True)
class RentalCountdown:
    """Exact target's native positive remaining-hour field and safe lower bound."""

    observed_at: datetime
    remaining_hours: int
    access_granted_until: datetime | None
    expiry_evidence: str | None

    @property
    def active(self) -> bool:
        return self.remaining_hours > 0


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
      const parentClasses = new Set(args.parentClasses);
      const anchorClasses = new Set(args.anchorClasses);
      const ancestorClasses = args.ancestorClasses.map(value => new Set(value));
      const sameSet = (actual, expected) => actual.length === expected.size &&
        actual.every(value => expected.has(value));
      const targetAnchors = [...parsed.querySelectorAll('a[href]')].filter(anchor => {
        try {
          const url = new URL(anchor.getAttribute('href'), target.origin);
          return url.origin === target.origin && url.pathname === target.pathname &&
            !url.username && !url.password && !url.search && !url.hash;
        } catch { return false; }
      });
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
          /^\s*\u6b8b\u308a\s*[0-9]+\s*\u6642\u9593\s*$/.test(node.textContent || ''));
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
            const match = /^\s*\u6b8b\u308a\s*([0-9]+)\s*\u6642\u9593\s*$/.exec(value.textContent || '');
            pairs.push({label, value, parent, hours: match ? Number(match[1]) : null});
          }
        }
        const valid = pairs.length === 1 && !unsafeHidden(anchor) &&
          !unsafeHidden(pairs[0].label) && !unsafeHidden(pairs[0].value) &&
          Number.isSafeInteger(pairs[0].hours) && pairs[0].hours > 0;
        return {
          labelCount: labels.length,
          valueCount: values.length,
          pairCount: pairs.length,
          hidden: targetAnchors.length !== 1 || (pairs.length === 1 &&
            (unsafeHidden(anchor) || unsafeHidden(pairs[0].label) || unsafeHidden(pairs[0].value))),
          hours: valid ? pairs[0].hours : null
        };
      });
      return {targetAnchorCount: targetAnchors.length, cards};
    }"""


async def parse_rental_history_html(
    page: Page,
    html: str,
    *,
    target: YanmagaEpisodeParts,
    observed_at: datetime,
) -> RentalCountdown | None:
    """Parse one exact native card; ambiguous, hidden, or malformed data is unknown."""

    if observed_at.tzinfo is None or observed_at.utcoffset() is None:
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
                "parentClasses": sorted(_PAIR_PARENT_CLASSES),
                "ancestorClasses": [sorted(classes) for classes in _ANCESTOR_CLASSES],
                "anchorClasses": sorted(_ANCHOR_CLASSES),
                "hideClass": _HIDE_CLASS,
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
    if (
        card.get("labelCount") != 1
        or card.get("valueCount") != 1
        or card.get("pairCount") != 1
        or card.get("hidden") is not False
        or isinstance(hours, bool)
        or not isinstance(hours, int)
        or hours <= 0
        or hours > _MAX_COUNTDOWN_HOURS
    ):
        return None
    return RentalCountdown(
        observed_at=observed_at.astimezone(UTC),
        remaining_hours=hours,
        # A parsed card alone has no response-freshness proof. Only the bounded
        # runtime fetch below may derive a finite grant lower bound.
        access_granted_until=None,
        expiry_evidence=None,
    )


async def fetch_rental_history_countdowns(
    page: Page,
    *,
    observed_mypage_href: str,
    targets: tuple[YanmagaEpisodeParts, ...],
) -> tuple[tuple[str, RentalCountdown], ...]:
    """Fetch MyPage and its observed history href in-page, returning target-only scalars."""

    try:
        current = urlsplit(page.url)
        mypage = urlsplit(observed_mypage_href)
        port = mypage.port
        current_query = parse_qsl(current.query, keep_blank_values=True)
    except ValueError:
        return ()
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
        return ()
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
      const readDocument = async href => {{
        const requested = new URL(href);
        if (requested.origin !== origin || requested.pathname !== '/mypage') return null;
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
        if (response.status !== 200 || !type.includes('text/html') || response.url !== href ||
            mimeType !== 'text/html' || response.redirected || !response.body ||
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
          if (size > args.maxBytes) {{ await reader.cancel(); return null; }}
          chunks.push(part.value);
        }}
        const joined = new Uint8Array(size);
        let offset = 0;
        for (const chunk of chunks) {{ joined.set(chunk, offset); offset += chunk.length; }}
        return new TextDecoder('utf-8').decode(joined);
      }};
      const mypageHref = safeUrl(args.mypageHref, '/mypage');
      if (!mypageHref || mypageHref.search || origin !== 'https://yanmaga.jp') return {{proofs:[]}};
      const mypageHtml = await readDocument(mypageHref.href);
      if (!mypageHtml) return {{proofs:[]}};
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
      if (links.length !== 1 || uniqueLinks.length !== 1) return {{proofs:[]}};
      const historyHref = safeUrl(uniqueLinks[0], '/mypage');
      if (!historyHref) return {{proofs:[]}};
      const historyHtml = await readDocument(historyHref.href);
      if (!historyHtml) return {{proofs:[]}};
      const parse = {parser};
      const proofs = [];
      for (const target of args.targets) {{
        const snapshot = parse({{html:historyHtml,targetUrl:target.targetUrl,
          label:args.label,labelClasses:args.labelClasses,valueClasses:args.valueClasses,
          parentClasses:args.parentClasses,ancestorClasses:args.ancestorClasses,
          anchorClasses:args.anchorClasses,hideClass:args.hideClass}});
        if (snapshot.targetAnchorCount !== 1 || !Array.isArray(snapshot.cards) ||
            snapshot.cards.length !== 1) continue;
        const card = snapshot.cards[0];
        if (card.labelCount === 1 && card.valueCount === 1 && card.pairCount === 1 &&
            card.hidden === false && Number.isSafeInteger(card.hours) && card.hours > 0 &&
            card.hours <= args.maxHours)
          proofs.push({{externalId:target.externalId,hours:card.hours}});
      }}
      return {{proofs}};
    }}"""
    try:
        raw = await page.evaluate(
            fetch_script,
            {
                "mypageHref": observed_mypage_href,
                "targets": target_args,
                "maxBytes": _MAX_HISTORY_BYTES,
                "maxHours": _MAX_COUNTDOWN_HOURS,
                "maxDateSkewMs": _MAX_DATE_SKEW_SECONDS * 1000,
                "label": "\u30ec\u30f3\u30bf\u30eb\u671f\u9593",
                "labelClasses": sorted(_LABEL_CLASSES),
                "valueClasses": sorted(_VALUE_CLASSES),
                "parentClasses": sorted(_PAIR_PARENT_CLASSES),
                "ancestorClasses": [sorted(classes) for classes in _ANCESTOR_CLASSES],
                "anchorClasses": sorted(_ANCHOR_CLASSES),
                "hideClass": _HIDE_CLASS,
                "historyLinkClasses": sorted(_HISTORY_LINK_CLASSES),
            },
        )
    except (PlaywrightError, PlaywrightTimeoutError, TypeError, ValueError):
        return ()
    if not isinstance(raw, dict) or not isinstance(raw.get("proofs"), list):
        return ()
    proofs: list[tuple[str, RentalCountdown]] = []
    seen: set[str] = set()
    for entry in raw["proofs"]:
        if not isinstance(entry, dict):
            return ()
        external_id = entry.get("externalId")
        hours = entry.get("hours")
        if (
            not isinstance(external_id, str)
            or external_id in seen
            or isinstance(hours, bool)
            or not isinstance(hours, int)
            or not 1 <= hours <= _MAX_COUNTDOWN_HOURS
        ):
            return ()
        seen.add(external_id)
        lower_bound = (
            observed_at
            - timedelta(seconds=_MAX_DATE_SKEW_SECONDS)
            + timedelta(hours=hours - 1)
            if hours > 1
            else None
        )
        proofs.append(
            (
                external_id,
                RentalCountdown(
                    observed_at=observed_at,
                    remaining_hours=hours,
                    access_granted_until=lower_bound,
                    expiry_evidence=(
                        "site_countdown_lower_bound" if lower_bound is not None else None
                    ),
                ),
            )
        )
    return tuple(proofs)



