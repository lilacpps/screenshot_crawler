"""Read-only Z4-0 chapter-list / access-state probe for Zeblack.

This probe is deliberately independent from the production Discovery layer.
It attaches to the shared Crawler Chrome through ``BrowserSession``, opens one
chapter-list URL, observes the DOM and bounded metadata responses, and never
clicks a chapter or access control.

Example::

    .\\.venv\\Scripts\\python.exe poc\\zeblack_discovery_probe.py `
        --url https://zebrack-comic.shueisha.co.jp/title/5123/chapter/list `
        --output-dir output\\zeblack_discovery_probe
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import re
from collections import defaultdict
from datetime import UTC, datetime
from itertools import pairwise
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from playwright.async_api import Page, Response

from screenshot_crawler.core.browser import BrowserSession, resolve_cdp_endpoint

DEFAULT_URL = "https://zebrack-comic.shueisha.co.jp/title/5123/chapter/list"
DEFAULT_OUTPUT_DIR = Path("output/zeblack_discovery_probe")
ZEBLACK_HOST = "zebrack-comic.shueisha.co.jp"
WAIT_TIMEOUT_MS = 15_000
MAX_SCROLLS = 30
MAX_RESPONSE_BODY = 2_000_000
MAX_RESPONSE_PREVIEW = 12_000
MAX_SUBTREE_CHARS = 16_000
MAX_SCRIPT_CHARS = 500_000

TITLE_LIST_RE = re.compile(r"^/title/(?P<title_id>[0-9]+)/chapter/list/?$")
CHAPTER_PATH_RE = re.compile(
    r"/title/(?P<title_id>[0-9]+)/chapter/(?P<chapter_id>[0-9]+)(?:/viewer)?(?:[/?#]|$)"
)
NUMERIC_LABEL_RE = re.compile(
    r"(?:第\s*)?(?P<number>\d+(?:\.\d+)?)\s*(?:話|回|話目|episode|Episode|#)?"
)
P_TOKEN_RE = re.compile(r"(?<![A-Za-z0-9])P(?![A-Za-z0-9])")
FREE_RE = re.compile(r"(?:^|[\s|/()[\]<>])(?:free|無料)(?:$|[\s|/()[\]<>])", re.IGNORECASE)
COIN_RE = re.compile(r"(?:coin|コイン|コインのみ|coin_only)", re.IGNORECASE)
RENTAL_RE = re.compile(r"(?:rental|レンタル|has_rented|rented)", re.IGNORECASE)
ACTIVE_RE = re.compile(r"(?:中|残り|期限|まで|expiry|expires|active)", re.IGNORECASE)
TICKET_RE = re.compile(r"(?:ticket|チケット|無料チケット)", re.IGNORECASE)
POINT_RE = re.compile(r"(?:point|ポイント)", re.IGNORECASE)
CHAPTER_FIELD_TERMS = (
    "chapter",
    "episode",
    "viewer",
    "access",
    "ticket",
    "rental",
    "coin",
    "point",
    "price",
    "status",
    "free",
)


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8", errors="replace")).hexdigest()


def safe_url(url: str, *, keep_query: bool = False) -> str:
    """Remove query/hash from observed network URLs by default."""

    try:
        parsed = urlsplit(url)
    except ValueError:
        return url
    return urlunsplit(
        (parsed.scheme, parsed.netloc, parsed.path, parsed.query if keep_query else "", "")
    )


def parse_target_list_url(url: str) -> dict[str, str] | None:
    """Parse only the canonical Zeblack chapter-list target shape."""

    try:
        parsed = urlsplit(url)
    except ValueError:
        return None
    if (parsed.scheme or "").lower() != "https" or (parsed.hostname or "").lower() != ZEBLACK_HOST:
        return None
    match = TITLE_LIST_RE.fullmatch(parsed.path)
    if match is None:
        return None
    return {"title_id": match.group("title_id"), "list_url": safe_url(url)}


def parse_chapter_identity(href: str, *, expected_title_id: str | None = None) -> dict[str, str] | None:
    """Extract the stable chapter identity and canonical viewer candidate."""

    try:
        parsed = urlsplit(href)
    except ValueError:
        return None
    if (parsed.hostname or "").lower() not in {"", ZEBLACK_HOST}:
        return None
    match = CHAPTER_PATH_RE.search(parsed.path)
    if match is None:
        return None
    title_id = match.group("title_id")
    if expected_title_id is not None and title_id != expected_title_id:
        return None
    chapter_id = match.group("chapter_id")
    return {
        "title_id": title_id,
        "chapter_id": chapter_id,
        "viewer_url": f"https://{ZEBLACK_HOST}/title/{title_id}/chapter/{chapter_id}/viewer",
    }


def normalize_text(value: Any) -> str:
    return " ".join(str(value or "").split())


def _flatten_signal_values(evidence: dict[str, Any]) -> list[str]:
    values: list[str] = []
    for key in ("texts", "classes", "attributes", "labels", "structured_values"):
        value = evidence.get(key, [])
        if isinstance(value, dict):
            value = [f"{item_key}={item_value}" for item_key, item_value in value.items()]
        if not isinstance(value, list):
            value = [value]
        values.extend(normalize_text(item) for item in value if normalize_text(item))
    return values


def classify_raw_access_state(evidence: dict[str, Any]) -> str:
    """Classify only explicit native-looking signals; conflicting signals stay unknown."""

    values = _flatten_signal_values(evidence)
    text = " | ".join(values)
    classes = " ".join(normalize_text(item) for item in evidence.get("classes", []))
    attributes = " ".join(normalize_text(item) for item in evidence.get("attributes", []))
    all_signals = f"{text} | {classes} | {attributes}"

    rental_active = bool(
        (RENTAL_RE.search(all_signals) or "閲覧期限" in all_signals or "閲覧中" in all_signals)
        and ACTIVE_RE.search(all_signals)
    )
    if rental_active or "レンタル中" in all_signals:
        return "rental-active"

    has_coin = bool(COIN_RE.search(all_signals))
    has_p = bool(P_TOKEN_RE.search(text)) or bool(
        POINT_RE.search(all_signals) and not COIN_RE.search(all_signals)
    )
    has_ticket = bool(TICKET_RE.search(all_signals))
    has_free = bool(FREE_RE.search(text))
    candidates = [
        state
        for state, present in (
            ("coin-only", has_coin),
            ("P", has_p),
            ("ticket-eligible", has_ticket),
            ("Free", has_free),
        )
        if present
    ]
    return candidates[0] if len(candidates) == 1 else "unknown"


def derive_current_access(raw_site_state: str) -> str:
    """Z4-0 observation hypothesis, not a production Site Policy mapping."""

    return {
        "Free": "ticket_now",
        "P": "ticket_later",
        "coin-only": "coin_only",
        "rental-active": "rental_active",
        "ticket-eligible": "ticket_eligible",
    }.get(raw_site_state, "unknown")


def classify_frontier(states: list[dict[str, Any]]) -> dict[str, Any]:
    """Describe contiguous observed derived states without reordering rows."""

    segments: list[dict[str, Any]] = []
    for row in states:
        state = str(row.get("derived_current_access") or "unknown")
        if segments and segments[-1]["state"] == state:
            segments[-1]["chapter_ids"].append(row.get("chapter_id"))
            segments[-1]["indices"].append(row.get("index"))
        else:
            segments.append(
                {
                    "state": state,
                    "chapter_ids": [row.get("chapter_id")],
                    "indices": [row.get("index")],
                }
            )
    allowed = {"ticket_now", "ticket_later", "ticket_eligible", "coin_only", "rental_active"}
    observed_ids = [row.get("chapter_id") for row in states if row.get("derived_current_access") in allowed]
    return {
        "observed": bool(observed_ids),
        "segments": segments,
        "ticket_now_chapter_ids": [
            row.get("chapter_id") for row in states if row.get("derived_current_access") == "ticket_now"
        ],
        "ticket_later_chapter_ids": [
            row.get("chapter_id") for row in states if row.get("derived_current_access") == "ticket_later"
        ],
        "coin_only_chapter_ids": [
            row.get("chapter_id") for row in states if row.get("derived_current_access") == "coin_only"
        ],
        "rental_active_chapter_ids": [
            row.get("chapter_id") for row in states if row.get("derived_current_access") == "rental_active"
        ],
        "ticket_eligible_chapter_ids": [
            row.get("chapter_id") for row in states if row.get("derived_current_access") == "ticket_eligible"
        ],
        "note": "Frontier is a snapshot of account-dependent observation; it is not a chapter attribute.",
    }


def extract_numeric_label(value: Any) -> float | None:
    text = normalize_text(value)
    match = NUMERIC_LABEL_RE.search(text)
    if match is None:
        return None
    try:
        return float(match.group("number"))
    except ValueError:
        return None


def infer_dom_order(chapters: list[dict[str, Any]]) -> dict[str, Any]:
    """Infer display direction while retaining raw DOM order as authority evidence."""

    labels = [extract_numeric_label(row.get("label")) for row in chapters]
    source = "visible_label"
    values = labels
    if len([value for value in values if value is not None]) < 2:
        source = "chapter_id"
        values = [extract_numeric_label(row.get("chapter_id")) for row in chapters]
    filtered = [value for value in values if value is not None]
    if len(filtered) < 2:
        return {"value": "unknown", "confidence": "unknown", "evidence_source": source}
    increasing = all(left <= right for left, right in pairwise(filtered))
    decreasing = all(left >= right for left, right in pairwise(filtered))
    if increasing and not decreasing:
        return {"value": "oldest-first", "confidence": "observed", "evidence_source": source}
    if decreasing and not increasing:
        return {"value": "latest-first", "confidence": "observed", "evidence_source": source}
    return {"value": "other-or-mixed", "confidence": "observed", "evidence_source": source}


def _key_text(key: Any) -> str:
    return re.sub(r"[^a-z0-9]", "", str(key).lower())


def _value_text(value: Any) -> str:
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))[:2000]
    return normalize_text(value)


def _chapter_id_from_record(record: dict[str, Any]) -> str | None:
    for key, value in record.items():
        normalized = _key_text(key)
        if normalized in {"chapterid", "episodeid", "readableproductid"} and value is not None:
            return str(value)
    for key, value in record.items():
        if ("chapter" in _key_text(key) or "episode" in _key_text(key)) and str(value).isdigit():
            return str(value)
    for key in ("href", "url", "viewer_url", "viewerUrl", "link"):
        value = record.get(key)
        if value:
            identity = parse_chapter_identity(str(value))
            if identity:
                return identity["chapter_id"]
    return None


def _title_id_from_record(record: dict[str, Any]) -> str | None:
    for key, value in record.items():
        if _key_text(key) in {"titleid", "workid", "seriesid"} and value is not None:
            return str(value)
    for key in ("href", "url", "viewer_url", "viewerUrl", "link"):
        value = record.get(key)
        if value:
            identity = parse_chapter_identity(str(value))
            if identity:
                return identity["title_id"]
    return None


def _record_is_chapter_candidate(record: dict[str, Any]) -> bool:
    chapter_id = _chapter_id_from_record(record)
    if chapter_id is None:
        return False
    keys = {_key_text(key) for key in record}
    values = " ".join(_value_text(value) for value in record.values())
    return bool(
        any("chapter" in key or "episode" in key for key in keys)
        or "/chapter/" in values
        or any(term in " ".join(keys) for term in CHAPTER_FIELD_TERMS)
    )


def extract_structured_chapter_records(value: Any, source_url: str = "") -> list[dict[str, Any]]:
    """Extract bounded chapter-shaped records from arbitrary JSON/embedded data."""

    found: list[dict[str, Any]] = []

    def visit(node: Any, path: str) -> None:
        if isinstance(node, list):
            for index, child in enumerate(node[:500]):
                visit(child, f"{path}[{index}]")
            return
        if not isinstance(node, dict):
            return
        if _record_is_chapter_candidate(node):
            filtered: dict[str, Any] = {
                "source_url": safe_url(source_url),
                "source_path": path,
                "chapter_id": _chapter_id_from_record(node),
                "title_id": _title_id_from_record(node),
            }
            for key, item in node.items():
                normalized = _key_text(key)
                if (
                    any(term in normalized for term in CHAPTER_FIELD_TERMS)
                    or normalized in {"id", "href", "url", "link", "name", "title", "label", "order", "index", "sequence"}
                ):
                    if isinstance(item, (str, int, float, bool)) or item is None:
                        filtered[str(key)] = item
                    elif isinstance(item, (dict, list)):
                        filtered[str(key)] = _value_text(item)
            found.append(filtered)
        for key, child in node.items():
            if isinstance(child, (dict, list)):
                visit(child, f"{path}.{key}")

    visit(value, "$" )
    return found


def structured_access_evidence(record: dict[str, Any]) -> dict[str, Any]:
    values: list[str] = []
    for key, value in record.items():
        normalized = _key_text(key)
        if any(term in normalized for term in ("access", "ticket", "rental", "coin", "point", "price", "status", "type", "free", "label")):
            values.append(f"{key}={_value_text(value)}")
    return {"structured_values": values}


def merge_structured_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for record in records:
        chapter_id = str(record.get("chapter_id") or "")
        if not chapter_id:
            continue
        current = merged.setdefault(chapter_id, {"chapter_id": chapter_id, "sources": []})
        source = record.get("source_url")
        if source and source not in current["sources"]:
            current["sources"].append(source)
        for key, value in record.items():
            if key not in {"source_url", "source_path"} and value not in (None, ""):
                current.setdefault(key, value)
        values = current.setdefault("structured_values", [])
        values.extend(item for item in structured_access_evidence(record)["structured_values"] if item not in values)
    return list(merged.values())


def _dom_chapter_snapshot_script() -> str:
    return r"""() => {
      const chapterRe = /\/title\/(\d+)\/chapter\/(\d+)(?:\/viewer)?(?:[/?#]|$)/;
      const visible = el => {
        const style = getComputedStyle(el);
        const rect = el.getBoundingClientRect();
        return style.display !== 'none' && style.visibility !== 'hidden' && rect.width > 0 && rect.height > 0;
      };
      const attrs = el => Object.fromEntries([...el.attributes].map(attr => [attr.name, ['src', 'href'].includes(attr.name) ? attr.value.split('?')[0] : attr.value]));
      const classes = el => typeof el.className === 'string' ? el.className : (el.getAttribute('class') || '');
      const text = el => (el.innerText || el.textContent || '').replace(/\s+/g, ' ').trim();
      const compactHtml = el => el.outerHTML.replace(/\s+/g, ' ').replace(/(https?:\/\/[^\s"']+)\?[^\s"']*/g, '$1').slice(0, 16000);
      const chapterLinks = [...document.querySelectorAll('a[href]')]
        .map((el, domOrder) => ({el, domOrder, href: el.getAttribute('href') || '', absolute: el.href || ''}))
        .filter(item => chapterRe.test(item.absolute || item.href));
      const rows = [];
      const seen = new Set();
      for (const item of chapterLinks) {
        const match = chapterRe.exec(item.absolute || item.href);
        if (!match) continue;
        const chapterId = match[2];
        if (seen.has(chapterId)) continue;
        seen.add(chapterId);
        const ancestors = [item.el];
        let current = item.el.parentElement;
        for (let depth = 0; current && depth < 7; depth += 1, current = current.parentElement) ancestors.push(current);
        const root = ancestors.find(candidate => candidate.tagName !== 'A' &&
          candidate.querySelectorAll('a[href]').length === 1) || item.el;
        const descendants = [...root.querySelectorAll('*')];
        const stateDescendants = descendants.filter(el => {
          const combined = `${classes(el)} ${el.getAttribute('aria-label') || ''} ${el.getAttribute('title') || ''} ${text(el)}`;
          return /badge|label|tag|status|access|price|cost|ticket|point|coin|free|rental|期限|残り|レンタル|無料|コイン/i.test(combined);
        }).slice(0, 80);
        const stateTexts = [...new Set([text(item.el), ...stateDescendants.map(text).filter(Boolean)])].slice(0, 80);
        const stateClasses = [...new Set([classes(root), ...stateDescendants.map(classes).filter(Boolean)])].slice(0, 80);
        const stateAttributes = stateDescendants.flatMap(el => Object.entries(attrs(el)))
          .filter(([name, value]) => /access|ticket|price|cost|rental|coin|point|free|status|type|state/i.test(`${name} ${value}`))
          .slice(0, 100)
          .map(([name, value]) => `${name}=${value}`);
        const priceMetadata = stateDescendants.map(el => ({tag: el.tagName.toLowerCase(), text: text(el), class: classes(el), attrs: attrs(el)}))
          .filter(item => /price|cost|coin|point|\bP\b|コイン|ポイント/i.test(`${item.text} ${item.class}`)).slice(0, 30);
        const rentalMetadata = stateDescendants.map(el => ({tag: el.tagName.toLowerCase(), text: text(el), class: classes(el), attrs: attrs(el)}))
          .filter(item => /rental|レンタル|期限|残り|まで|expiry|active/i.test(`${item.text} ${item.class}`)).slice(0, 30);
        const labels = [
          ...stateDescendants.map(text),
          text(item.el).split(/\n| {2,}/).map(value => value.trim()).filter(Boolean),
        ].flat().filter(Boolean);
        rows.push({
          dom_order: item.domOrder,
          chapter_id: chapterId,
          title_id: match[1],
          href: item.href || item.absolute,
          absolute_href: item.absolute,
          label_candidates: [...new Set(labels)].slice(0, 30),
          visible_text: visible(root) ? text(root) : '',
          raw_text: text(root),
          inner_text: root.innerText || '',
          aria_label: root.getAttribute('aria-label'),
          title_attribute: root.getAttribute('title'),
          class: classes(root),
          data_attributes: Object.fromEntries(Object.entries(attrs(root)).filter(([name]) => name.startsWith('data-'))),
          disabled: root.matches(':disabled') || root.getAttribute('aria-disabled') === 'true' || !!root.querySelector(':disabled,[aria-disabled="true"]'),
          visible: visible(root),
          badge_metadata: stateDescendants.map(el => ({tag: el.tagName.toLowerCase(), text: text(el), class: classes(el), aria_label: el.getAttribute('aria-label'), title: el.getAttribute('title'), data: Object.fromEntries(Object.entries(attrs(el)).filter(([name]) => name.startsWith('data-')))})).slice(0, 50),
          badge_text: [...new Set(stateTexts)].slice(0, 80),
          badge_class: [...new Set(stateClasses)].slice(0, 80),
          state_attributes: [...new Set(stateAttributes)].slice(0, 100),
          price_metadata: priceMetadata,
          rental_metadata: rentalMetadata,
          button_link_state: descendants.filter(el => ['A','BUTTON'].includes(el.tagName)).slice(0, 40).map(el => ({tag: el.tagName.toLowerCase(), text: text(el), href: el.getAttribute('href'), disabled: el.matches(':disabled') || el.getAttribute('aria-disabled') === 'true', aria_label: el.getAttribute('aria-label'), title: el.getAttribute('title'), class: classes(el)})),
          compact_subtree: root.outerHTML.replace(/\s+/g, ' ').slice(0, 16000),
        });
      }
      const controls = [...document.querySelectorAll('a,button,[role="button"]')].map(el => ({
        text: text(el), aria_label: el.getAttribute('aria-label'), title: el.getAttribute('title'), class: classes(el), href: el.getAttribute('href'),
      })).filter(item => /pagination|page|もっと見る|次へ|前へ|load more|more chapters|chapter/i.test(`${item.text} ${item.aria_label || ''} ${item.title || ''} ${item.class}`)).slice(0, 80);
      const genericCandidates = [...document.querySelectorAll('*')]
        .filter(el => /^#\s*\d+\b/.test(text(el)) && text(el).length < 700)
        .filter(el => ![...el.children].some(child => /^#\s*\d+\b/.test(text(child))))
        .map((el, domOrder) => {
          const ancestors = [el];
          let current = el.parentElement;
          for (let depth = 0; current && depth < 6; depth += 1, current = current.parentElement) ancestors.push(current);
          const root = ancestors.find(candidate => /^chapter\d+$/i.test(candidate.id || '') || candidate.hasAttribute('data-chapter-id')) || el;
          const rootDescendants = [...root.querySelectorAll('*')];
          const stateDescendants = rootDescendants.filter(child => /badge|label|tag|status|access|price|cost|ticket|point|coin|free|rental|期限|残り|レンタル|無料|コイン/i.test(`${classes(child)} ${child.getAttribute('aria-label') || ''} ${child.getAttribute('title') || ''} ${text(child)}`)).slice(0, 80);
          return {
          dom_order: domOrder,
          tag: el.tagName.toLowerCase(),
          text: text(el),
          inner_text: el.innerText || '',
          class: classes(el),
          attrs: attrs(el),
          visible: visible(root),
          ancestors: ancestors.slice(1).map(candidate => ({tag: candidate.tagName.toLowerCase(), id: candidate.id || null, class: classes(candidate), attrs: attrs(candidate), text: text(candidate).slice(0, 700)})),
          row_root: {tag: root.tagName.toLowerCase(), id: root.id || null, class: classes(root), attrs: attrs(root), text: text(root), inner_text: root.innerText || '', compact_subtree: compactHtml(root)},
          state_descendants: stateDescendants.map(child => ({tag: child.tagName.toLowerCase(), text: text(child), class: classes(child), aria_label: child.getAttribute('aria-label'), title: child.getAttribute('title'), attrs: attrs(child)})),
          icon_metadata: [...root.querySelectorAll('img,svg')].slice(0, 40).map(icon => ({tag: icon.tagName.toLowerCase(), alt: icon.getAttribute('alt'), src_kind: (icon.getAttribute('src') || '').startsWith('data:') ? 'data' : (icon.getAttribute('src') || '').startsWith('blob:') ? 'blob' : 'url', class: classes(icon), attrs: attrs(icon)})),
          buttons: [...root.querySelectorAll('a,button,[role="button"]')].slice(0, 20).map(child => ({
            tag: child.tagName.toLowerCase(), text: text(child), href: child.getAttribute('href'),
            aria_label: child.getAttribute('aria-label'), title: child.getAttribute('title'), class: classes(child),
            disabled: child.matches(':disabled') || child.getAttribute('aria-disabled') === 'true',
          })),
          compact_subtree: compactHtml(root),
        }; }).slice(0, 500);
      const bodyText = text(document.body);
      const loginIndicators = [...new Set([...document.querySelectorAll('a,button,[role="button"]')].map(text).filter(Boolean).filter(value => /ログイン|ログアウト|マイページ|sign in|sign out|account/i.test(value)))].slice(0, 30);
      return {
        url: location.href,
        document_title: document.title,
        body_visible_text_preview: bodyText.slice(0, 5000),
        rows,
        generic_candidates: genericCandidates,
        all_chapter_link_count: chapterLinks.length,
        pagination_candidates: controls,
        login_indicators: loginIndicators,
        scroll: {scroll_y: window.scrollY, viewport_height: window.innerHeight, scroll_height: document.documentElement.scrollHeight, body_scroll_height: document.body ? document.body.scrollHeight : null},
      };
    }"""


async def collect_dom(page: Page) -> dict[str, Any]:
    return await page.evaluate(_dom_chapter_snapshot_script())


def dom_candidate_rows(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    rows = snapshot.get("rows") or []
    return rows if rows else list(snapshot.get("generic_candidates") or [])


async def collect_embedded_data(page: Page) -> list[dict[str, Any]]:
    scripts = await page.locator("script").evaluate_all(
        f"""els => els.map((el, index) => ({{
          index,
          id: el.id || null,
          type: el.getAttribute('type'),
          src: el.getAttribute('src'),
          text: (el.textContent || '').slice(0, {MAX_SCRIPT_CHARS}),
          length: (el.textContent || '').length
        }}))"""
    )
    payloads: list[dict[str, Any]] = []
    for script in scripts:
        script_text = str(script.get("text") or "")
        is_json = str(script.get("type") or "").lower() == "application/json" or script.get("id") in {"__NEXT_DATA__", "__NUXT_DATA__"}
        if not is_json and not any(term in script_text.lower() for term in ("chapter", "episode", "ticket", "rental", "coin")):
            continue
        parsed: Any = None
        parse_error: str | None = None
        if is_json:
            try:
                parsed = json.loads(script_text)
            except (TypeError, ValueError) as exc:
                parse_error = str(exc)
        records = extract_structured_chapter_records(parsed, f"embedded-script:{script.get('index')}") if parsed is not None else []
        payloads.append(
            {
                "index": script.get("index"),
                "id": script.get("id"),
                "type": script.get("type"),
                "src": safe_url(str(script.get("src") or "")),
                "length": script.get("length"),
                "parse_error": parse_error,
                "chapter_record_count": len(records),
                "chapter_records": records,
                "text_preview": script_text[:4000] if records or parse_error else None,
            }
        )
    return payloads


async def install_network_observer(page: Page) -> tuple[list[dict[str, Any]], list[asyncio.Task[Any]]]:
    records: list[dict[str, Any]] = []
    tasks: list[asyncio.Task[Any]] = []

    async def capture_body(response: Response, record: dict[str, Any]) -> None:
        content_type = (response.headers.get("content-type") or "").lower()
        try:
            body = await response.body()
        except Exception as exc:  # noqa: BLE001 - observation must survive races
            record["body_error"] = type(exc).__name__
            return
        record["body_bytes"] = len(body)
        if len(body) > MAX_RESPONSE_BODY:
            record["body_skipped"] = "max_response_body"
            return
        if "protobuf" in content_type:
            record["body_prefix_hex"] = body[:256].hex()
        text = body.decode("utf-8", errors="replace")
        record["body_sha256"] = sha256_text(text)
        if "json" in content_type or text.lstrip().startswith(("{", "[")):
            try:
                parsed = json.loads(text)
            except (TypeError, ValueError) as exc:
                record["json_parse_error"] = str(exc)
            else:
                structured = extract_structured_chapter_records(parsed, record["url"])
                record["structured_records"] = structured
                record["structured_record_count"] = len(structured)
                if structured:
                    record["body_preview"] = text[:MAX_RESPONSE_PREVIEW]
        elif ("html" in content_type or response.request.resource_type == "document") and (
            "/chapter/" in text or "chapter" in text.lower()
        ):
            record["body_preview"] = text[:MAX_RESPONSE_PREVIEW]

    def on_response(response: Response) -> None:
        request = response.request
        content_type = response.headers.get("content-type")
        resource_type = request.resource_type
        should_read = resource_type in {"document", "xhr", "fetch"} or "json" in (content_type or "").lower()
        record: dict[str, Any] = {
            "sequence": len(records),
            "timestamp": now_iso(),
            "url": safe_url(response.url),
            "method": request.method,
            "status": response.status,
            "resource_type": resource_type,
            "content_type": content_type,
            "content_length": response.headers.get("content-length"),
            "body_observed": False,
        }
        records.append(record)
        if should_read:
            record["body_observed"] = True
            tasks.append(asyncio.create_task(capture_body(response, record)))

    page.on("response", on_response)
    return records, tasks


def _row_to_chapter(row: dict[str, Any], *, expected_title_id: str) -> dict[str, Any] | None:
    identity = parse_chapter_identity(str(row.get("absolute_href") or row.get("href") or ""), expected_title_id=expected_title_id)
    if identity is None:
        raw_href = str(row.get("href") or "")
        chapter_id = str(row.get("chapter_id") or "")
        if not chapter_id.isdigit():
            return None
        identity = {
            "title_id": expected_title_id,
            "chapter_id": chapter_id,
            "viewer_url": f"https://{ZEBLACK_HOST}/title/{expected_title_id}/chapter/{chapter_id}/viewer",
        }
        raw_href = raw_href or identity["viewer_url"]
    labels = [str(value) for value in row.get("label_candidates") or [] if normalize_text(value)]
    label = next((value for value in labels if extract_numeric_label(value) is not None), labels[0] if labels else None)
    evidence = {
        "texts": row.get("badge_text") or [],
        "classes": row.get("badge_class") or [],
        "attributes": row.get("state_attributes") or [],
        "labels": labels,
    }
    raw_site_state = classify_raw_access_state(evidence)
    return {
        "index": row.get("dom_order"),
        "chapter_id": identity["chapter_id"],
        "title_id": identity["title_id"],
        "href": row.get("href") or row.get("absolute_href"),
        "canonical_viewer_url": identity["viewer_url"],
        "label": label,
        "label_candidates": labels,
        "raw_text": row.get("raw_text"),
        "visible_text": row.get("visible_text"),
        "inner_text": row.get("inner_text"),
        "aria_label": row.get("aria_label"),
        "title_attribute": row.get("title_attribute"),
        "class": row.get("class"),
        "data_attributes": row.get("data_attributes") or {},
        "button_link_state": row.get("button_link_state") or [],
        "disabled": bool(row.get("disabled")),
        "visible": bool(row.get("visible")),
        "badge_metadata": row.get("badge_metadata") or [],
        "badge_text": row.get("badge_text") or [],
        "badge_class": row.get("badge_class") or [],
        "price_metadata": row.get("price_metadata") or [],
        "rental_metadata": row.get("rental_metadata") or [],
        "compact_subtree": row.get("compact_subtree"),
        "dom_raw_site_state": raw_site_state,
        "structured_raw_site_state": "unknown",
        "raw_site_state": raw_site_state,
        "raw_state_evidence": evidence,
        "derived_current_access": derive_current_access(raw_site_state),
        "derived_mapping_hypothesis": True,
    }


def _generic_candidate_to_row(candidate: dict[str, Any], *, expected_title_id: str) -> dict[str, Any] | None:
    """Adapt non-anchor chapter cards without treating ``#N`` as chapter_id."""

    root = candidate.get("row_root") or {}
    candidates: list[dict[str, Any]] = [root, candidate]
    candidates.extend(item for item in candidate.get("ancestors") or [] if isinstance(item, dict))
    chapter_id: str | None = None
    title_id = expected_title_id
    identity_source = None
    href: str | None = None
    for item in candidates:
        attrs = item.get("attrs") or {}
        item_id = str(item.get("id") or attrs.get("id") or "")
        chapter_match = re.fullmatch(r"chapter(?P<chapter_id>\d+)", item_id, re.IGNORECASE)
        if chapter_match:
            chapter_id = chapter_match.group("chapter_id")
            identity_source = f"id:{item_id}"
        for key, value in attrs.items():
            normalized = _key_text(key)
            if normalized in {"chapterid", "episodeid", "readableproductid"} and str(value).isdigit():
                chapter_id = str(value)
                identity_source = f"attribute:{key}"
            if normalized in {"titleid", "workid", "seriesid"} and str(value).isdigit():
                title_id = str(value)
            if key in {"href", "data-href"} and value:
                href = str(value)
        for button in item.get("buttons") or []:
            if button.get("href"):
                href = str(button["href"])
                parsed = parse_chapter_identity(href, expected_title_id=expected_title_id)
                if parsed:
                    chapter_id = parsed["chapter_id"]
                    title_id = parsed["title_id"]
                    identity_source = "descendant_href"
    if chapter_id is None:
        return None
    canonical = f"https://{ZEBLACK_HOST}/title/{title_id}/chapter/{chapter_id}/viewer"
    raw_text = root.get("text") or candidate.get("text") or candidate.get("inner_text") or ""
    state_descendants = candidate.get("state_descendants") or []
    icon_metadata = candidate.get("icon_metadata") or []
    state_texts = [raw_text, candidate.get("text") or ""] + [item.get("text") or "" for item in state_descendants]
    state_texts.extend(str(item.get("alt") or "") for item in icon_metadata)
    state_classes = [root.get("class") or "", candidate.get("class") or ""]
    state_classes.extend(item.get("class") or "" for item in state_descendants)
    state_attributes = [f"{key}={value}" for key, value in (root.get("attrs") or {}).items()]
    state_attributes.extend(f"{key}={value}" for key, value in (candidate.get("attrs") or {}).items())
    state_attributes.extend(
        f"{key}={value}" for item in state_descendants for key, value in (item.get("attrs") or {}).items()
    )
    state_classes.extend(item.get("class") or "" for item in icon_metadata)
    state_attributes.extend(
        f"{key}={value}" for item in icon_metadata for key, value in (item.get("attrs") or {}).items()
    )
    for ancestor in candidate.get("ancestors") or []:
        state_classes.append(str(ancestor.get("class") or ""))
        state_attributes.extend(f"{key}={value}" for key, value in (ancestor.get("attrs") or {}).items())
    labels = [line.strip() for line in re.split(r"\n| {2,}", str(candidate.get("text") or "")) if line.strip()]
    labels = labels or [str(raw_text).strip()]
    evidence = {"texts": state_texts, "classes": state_classes, "attributes": state_attributes, "labels": labels}
    raw_state = classify_raw_access_state(evidence)
    price_metadata = [item for item in state_descendants if re.search(r"price|cost|coin|point|\bP\b|コイン|ポイント", f"{item.get('text', '')} {item.get('class', '')}", re.IGNORECASE)]
    rental_metadata = [item for item in state_descendants if re.search(r"rental|レンタル|期限|残り|まで|expiry|active", f"{item.get('text', '')} {item.get('class', '')}", re.IGNORECASE)]
    return {
        "index": candidate.get("dom_order"),
        "chapter_id": chapter_id,
        "title_id": title_id,
        "href": href,
        "canonical_viewer_url": canonical,
        "identity_source": identity_source,
        "label": next((label for label in labels if extract_numeric_label(label) is not None), labels[0] if labels else None),
        "label_candidates": labels[:30],
        "raw_text": raw_text,
        "visible_text": raw_text if candidate.get("visible") else "",
        "inner_text": root.get("inner_text") or candidate.get("inner_text"),
        "aria_label": (root.get("attrs") or {}).get("aria-label") or (candidate.get("attrs") or {}).get("aria-label"),
        "title_attribute": (root.get("attrs") or {}).get("title") or (candidate.get("attrs") or {}).get("title"),
        "class": root.get("class") or candidate.get("class"),
        "data_attributes": {key: value for key, value in (root.get("attrs") or {}).items() if key.startswith("data-")},
        "button_link_state": candidate.get("buttons") or [],
        "disabled": any(bool(button.get("disabled")) for button in candidate.get("buttons") or []),
        "visible": bool(candidate.get("visible")),
        "badge_metadata": [{"kind": "icon", **item} for item in icon_metadata] + state_descendants,
        "badge_text": state_texts,
        "badge_class": state_classes,
        "price_metadata": price_metadata,
        "rental_metadata": rental_metadata,
        "compact_subtree": root.get("compact_subtree") or candidate.get("compact_subtree"),
        "dom_raw_site_state": raw_state,
        "structured_raw_site_state": "unknown",
        "raw_site_state": raw_state,
        "raw_state_evidence": evidence,
        "derived_current_access": derive_current_access(raw_state),
        "derived_mapping_hypothesis": True,
    }


def _structured_state_for_chapter(record: dict[str, Any]) -> str:
    return classify_raw_access_state(structured_access_evidence(record))


def merge_structured_into_chapters(chapters: list[dict[str, Any]], structured: list[dict[str, Any]]) -> dict[str, Any]:
    by_id = {str(record.get("chapter_id")): record for record in structured if record.get("chapter_id")}
    matched = 0
    conflicts = 0
    for chapter in chapters:
        record = by_id.get(str(chapter["chapter_id"]))
        if record is None:
            continue
        matched += 1
        state = _structured_state_for_chapter(record)
        chapter["structured_metadata"] = record
        chapter["structured_raw_site_state"] = state
        dom_state = chapter.get("dom_raw_site_state")
        if dom_state != "unknown" and state != "unknown" and dom_state != state:
            conflicts += 1
        if dom_state == "unknown" and state != "unknown":
            chapter["raw_site_state"] = state
            chapter["derived_current_access"] = derive_current_access(state)
            chapter["raw_state_source"] = "structured_only"
        elif dom_state == state or state == "unknown":
            chapter["raw_state_source"] = "dom_or_unresolved"
        else:
            chapter["raw_site_state"] = "unknown"
            chapter["derived_current_access"] = "unknown"
            chapter["raw_state_source"] = "conflicting_dom_and_structured"
    return {"matched_chapters": matched, "conflicting_states": conflicts}


def build_question_answers(
    *, listing: dict[str, Any], chapters: list[dict[str, Any]], structured: list[dict[str, Any]], frontier: dict[str, Any]
) -> dict[str, Any]:
    complete_initial = listing.get("initial_rows") == listing.get("total_rows") and listing.get("total_rows", 0) > 0
    identity_ok = bool(chapters) and len({row.get("chapter_id") for row in chapters}) == len(chapters)
    states = {row.get("derived_current_access") for row in chapters}
    structured_access_fields = any(
        any(term in str(key).lower() for term in ("access", "ticket", "rental", "coin", "point", "price", "status", "type"))
        for record in structured
        for key in record
    )
    stable_eligible = any(
        any(term in " ".join(str(value).lower() for value in record.values()) for term in ("eligible", "ticket_eligible", "ticketeligible"))
        for record in structured
    )
    ticket_icon_observed = "ticket-eligible" in {row.get("raw_site_state") for row in chapters}
    rental_rows = [row for row in chapters if row.get("raw_site_state") == "rental-active"]
    rental_metadata_observed = any(row.get("rental_metadata") for row in rental_rows)
    return {
        "Q1_all_chapters_one_list_load": "yes" if complete_initial else "no_or_not_proven",
        "Q2_chapter_id_stable_external_id": "yes" if identity_ok else "no_or_not_proven",
        "Q3_dom_order": listing.get("dom_order", {}).get("value", "unknown"),
        "Q4_Free_stable_signal": "yes" if "Free" in {row.get("raw_site_state") for row in chapters} else "not_observed",
        "Q5_P_stable_signal": "yes" if "P" in {row.get("raw_site_state") for row in chapters} else "not_observed",
        "Q6_P_vs_coin_only_stable": "yes" if {"P", "coin-only"}.issubset({row.get("raw_site_state") for row in chapters}) and not any(row.get("raw_site_state") == "unknown" for row in chapters) else "not_proven",
        "Q7_rental_active_stable": "yes" if "rental-active" in {row.get("raw_site_state") for row in chapters} else "not_observed",
        "Q8_rental_expiry_or_remaining_time": "yes" if rental_metadata_observed else "not_observed",
        "Q9_non_DOM_structured_access": "yes" if structured_access_fields else "not_found",
        "Q10_P_stable_ticket_eligible_type": (
            "partial: explicit ticket-eligible icon is stable-looking, but P/point icon equivalence is not proven"
            if ticket_icon_observed
            else "yes" if stable_eligible else "not_proven"
        ),
        "Q11_ticket_now_account_dependent_flag_separate": "not_proven_without_explicit_current-eligibility_field",
        "Q12_avoid_full_refresh_after_consumption": "conditional_on_stable_ticket_eligible_plus_dynamic_current_flag; not established by this snapshot",
        "Q13_chapter_id_bounded_boundary": "yes" if identity_ok and all(row.get("canonical_viewer_url") for row in chapters) else "not_proven",
        "Q14_recommended_authority": (
            "structured API/embedded JSON candidate, with DOM cross-check"
            if structured and listing.get("structured_chapter_count") == len(chapters)
            else "DOM, until a complete structured listing is found"
        ),
        "observed_state_set": sorted(state for state in states if state),
        "frontier_observed": frontier.get("observed", False),
    }


def make_summary(report: dict[str, Any]) -> str:
    listing = report["listing"]
    questions = report["questions"]
    frontier = report["ticket_frontier"]
    chapters = report["chapters"]
    structured = report["network"].get("structured_chapter_count", 0)
    state_counts: dict[str, int] = defaultdict(int)
    for chapter in chapters:
        state_counts[str(chapter.get("raw_site_state"))] += 1
    lines = [
        "# Zeblack Z4-0 chapter-list / access-state probe",
        "",
        "## 1. Target / account context",
        "",
        f"- target: `{report['target']}`",
        f"- title_id: `{report['title_id']}`; document title: `{report.get('document_title') or ''}`",
        f"- account context: `{report['account_context']}` (visible indicators only; cookies/storage were not inspected)",
        "- This is research-only. No login, click, ticket use, purchase, rental start, ad view, or viewer transition was performed.",
        "",
        "## 2. Chapter-list structure",
        "",
        f"- initial unique chapter rows: `{listing.get('initial_rows')}`; after scroll: `{listing.get('after_scroll_rows')}`; final: `{listing.get('total_rows')}`",
        f"- all chapter links observed: `{listing.get('all_chapter_link_count')}`; pagination candidates: `{len(listing.get('pagination_candidates', []))}`",
        "",
        "## 3. Chapter identity",
        "",
        f"- parsed chapter IDs: `{len(chapters)}`; unique: `{len({row.get('chapter_id') for row in chapters})}`",
        f"- URL candidate: `/title/{report['title_id']}/chapter/{{chapter_id}}/viewer` for each parsed row.",
        "- The artifact keeps href, label, DOM index, raw text, compact subtree, and data attributes per row.",
        "",
        "## 4. Listing order",
        "",
        f"- DOM order inference: `{listing.get('dom_order', {}).get('value')}`; evidence: `{listing.get('dom_order', {}).get('evidence_source')}`",
        "- DOM order is preserved. The probe does not sort chapters.",
        "- recommended canonical Discovery order: `latest-first` per bounded Discovery policy; Web ticket consumption order: `not tested`.",
        "",
        "## 5. Complete-list / lazy-load behavior",
        "",
        f"- initial/all-at-once: `{listing.get('initial_rows') == listing.get('total_rows') and listing.get('total_rows', 0) > 0}`; lazy loading observed: `{listing.get('lazy_loading')}`; virtualized: `{listing.get('virtualized')}`",
        f"- scroll samples: `{len(listing.get('scroll_samples', []))}`; network-after-scroll responses: `{listing.get('network_after_scroll_count')}`",
        "",
        "## 6. DOM access-state signals",
        "",
        f"- raw state counts: `{dict(state_counts)}`",
        "- Raw labels/signals and the derived mapping are stored separately. CSS module classes are evidence only, not production selector authority.",
        "",
        "## 7. Structured API/data signals",
        "",
        f"- relevant endpoints: `{json.dumps(report['network'].get('relevant_endpoints', []), ensure_ascii=False)}`",
        f"- structured listing found: `{report['network'].get('structured_listing_found')}`; structured chapter count: `{structured}`",
        f"- DOM/structured matched chapters: `{report['network'].get('dom_structured_matched_chapters')}`; conflicts: `{report['network'].get('dom_structured_conflicts')}`",
        "",
        "## 8. Free observation",
        "",
        f"- `Free` rows: `{questions.get('Q4_Free_stable_signal')}`; raw `Free` is only mapped to `ticket_now` as a Z4-0 hypothesis.",
        "",
        "## 9. P observation",
        "",
        f"- `P` rows: `{questions.get('Q5_P_stable_signal')}`; raw `P` is only mapped to `ticket_later` as a Z4-0 hypothesis.",
        "",
        "## 10. Coin-only observation",
        "",
        f"- P vs coin-only: `{questions.get('Q6_P_vs_coin_only_stable')}`; coin-only rows: `{frontier.get('coin_only_chapter_ids', [])}`.",
        "",
        "## 11. Rental-active observation",
        "",
        f"- rental-active: `{questions.get('Q7_rental_active_stable')}`; rental rows: `{frontier.get('rental_active_chapter_ids', [])}`.",
        "- Rental origin (ticket/point/coin) is not inferred from current DOM when it is not explicitly represented.",
        "",
        "## 12. Ticket frontier",
        "",
        f"- observed: `{frontier.get('observed')}`; segments: `{json.dumps(frontier.get('segments', []), ensure_ascii=False)}`",
        f"- ticket_now: `{frontier.get('ticket_now_chapter_ids', [])}`; ticket_later: `{frontier.get('ticket_later_chapter_ids', [])}`",
        f"- explicit ticket-eligible icon candidates: `{frontier.get('ticket_eligible_chapter_ids', [])}`",
        "- Any ticket frontier is account-dependent and can change after one ticket is consumed; it is not persisted as a chapter-intrinsic property.",
        "",
        "## 13. Stable vs dynamic state",
        "",
        "- Candidate stable attributes: chapter_id, label/order, viewer URL, explicit ticket-eligible icon, point icon, and coin icon.",
        "- Candidate dynamic attributes: current ticket availability, rental-active, and expiry/remaining time.",
        f"- Stable ticket-eligibility flag observed: `{questions.get('Q10_P_stable_ticket_eligible_type')}`; separate current flag: `{questions.get('Q11_ticket_now_account_dependent_flag_separate')}`.",
        "",
        "## 14. Implications for Discovery",
        "",
        "- Do not make `P == permanently non-ticket` a production rule. Treat it as a current account snapshot unless a stable eligibility field is confirmed.",
        f"- authority candidate: `{questions.get('Q14_recommended_authority')}`.",
        "",
        "## 15. Implications for bounded Discovery",
        "",
        f"- chapter_id to viewer boundary correspondence: `{questions.get('Q13_chapter_id_bounded_boundary')}`.",
        "- `/title/{title_id}/chapter/{chapter_id}/viewer` is a candidate boundary URL; bounded support remains unimplemented.",
        "",
        "## 16. Implications for future Site Policy",
        "",
        "- Separate site-intrinsic `ticket_eligible` / `coin_only` from account-dependent `currently_ticket_available` / `rental_active`.",
        "- A future policy must refresh or reconcile dynamic eligibility after consumption; Z4-0 did not consume anything and cannot prove the refresh-free design.",
        "",
        "## 17. Remaining unknowns",
        "",
        f"- `{'; '.join(report.get('unknowns', [])) or 'none recorded'}`",
        "",
        "## Q1-Q14 answers",
        "",
    ]
    for key, value in questions.items():
        if key.startswith("Q"):
            lines.append(f"- {key}: `{value}`")
    return "\n".join(lines) + "\n"


class ZeblackDiscoveryProbe:
    """Bounded read-only chapter-list observer."""

    def __init__(self, page: Page, output_dir: Path, target: str, title_id: str) -> None:
        self.page = page
        self.output_dir = output_dir
        self.target = target
        self.title_id = title_id
        self.network_records: list[dict[str, Any]] = []
        self.network_tasks: list[asyncio.Task[Any]] = []
        self.errors: list[str] = []

    async def wait_network_idle(self) -> None:
        try:
            await self.page.wait_for_load_state("networkidle", timeout=WAIT_TIMEOUT_MS)
        except Exception as exc:  # noqa: BLE001 - a live page may poll forever
            self.errors.append(f"networkidle not reached: {type(exc).__name__}")

    async def scroll_to_end(self) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        initial = await collect_dom(self.page)
        samples: list[dict[str, Any]] = []
        previous_count = len(dom_candidate_rows(initial))
        previous_height = int((initial.get("scroll") or {}).get("scroll_height") or 0)
        stable_rounds = 0
        for iteration in range(MAX_SCROLLS):
            before_network = len(self.network_records)
            await self.page.evaluate("window.scrollTo(0, document.documentElement.scrollHeight)")
            await self.page.wait_for_timeout(500)
            current = await collect_dom(self.page)
            rows = dom_candidate_rows(current)
            scroll = current.get("scroll") or {}
            row_count = len(rows)
            height = int(scroll.get("scroll_height") or 0)
            sample = {
                "iteration": iteration + 1,
                "row_count": row_count,
                "scroll_y": scroll.get("scroll_y"),
                "scroll_height": height,
                "network_response_count_delta": len(self.network_records) - before_network,
            }
            samples.append(sample)
            if row_count == previous_count and height == previous_height:
                stable_rounds += 1
            else:
                stable_rounds = 0
            previous_count = row_count
            previous_height = height
            if stable_rounds >= 2 or scroll.get("scroll_y", 0) + scroll.get("viewport_height", 0) >= height:
                break
        return initial, samples

    async def run(self) -> dict[str, Any]:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        (self.output_dir / "dom").mkdir(parents=True, exist_ok=True)
        (self.output_dir / "network" / "relevant_payloads").mkdir(parents=True, exist_ok=True)
        self.network_records, self.network_tasks = await install_network_observer(self.page)
        try:
            await self.page.goto(self.target, wait_until="domcontentloaded", timeout=30_000)
        except Exception as exc:  # noqa: BLE001 - write artifact even on blocked navigation
            self.errors.append(f"page.goto failed: {type(exc).__name__}: {exc}")
        await self.wait_network_idle()
        initial, scroll_samples = await self.scroll_to_end()
        final = await collect_dom(self.page)
        embedded = await collect_embedded_data(self.page)
        await asyncio.gather(*self.network_tasks, return_exceptions=True)

        all_structured_records: list[dict[str, Any]] = []
        relevant_endpoints: list[str] = []
        response_payload_index = 0
        for record in self.network_records:
            response_records = record.pop("structured_records", [])
            if response_records:
                all_structured_records.extend(response_records)
                relevant_endpoints.append(str(record.get("url")))
                payload_path = self.output_dir / "network" / "relevant_payloads" / f"response_{response_payload_index:03d}.json"
                write_json(payload_path, {"source": record.get("url"), "records": response_records})
                record["relevant_payload_path"] = str(payload_path.relative_to(self.output_dir))
                response_payload_index += 1
        for payload in embedded:
            records = payload.get("chapter_records") or []
            if records:
                all_structured_records.extend(records)
                payload_path = self.output_dir / "network" / "relevant_payloads" / f"embedded_{payload.get('index'):03d}.json"
                write_json(payload_path, {"source": f"embedded-script:{payload.get('index')}", "records": records})
                payload["relevant_payload_path"] = str(payload_path.relative_to(self.output_dir))
        structured = merge_structured_records(all_structured_records)

        chapters: list[dict[str, Any]] = []
        seen: set[str] = set()
        candidate_rows = dom_candidate_rows(final)
        for row in candidate_rows:
            chapter = _row_to_chapter(row, expected_title_id=self.title_id)
            if chapter is None and row in (final.get("generic_candidates") or []):
                chapter = _generic_candidate_to_row(row, expected_title_id=self.title_id)
            if chapter is None or chapter["chapter_id"] in seen:
                continue
            seen.add(chapter["chapter_id"])
            chapters.append(chapter)
        merge_result = merge_structured_into_chapters(chapters, structured)
        dom_order = infer_dom_order(chapters)
        frontier = classify_frontier(chapters)
        pagination_candidates = final.get("pagination_candidates") or []
        structured_listing_found = bool(structured)
        listing = {
            "initial_rows": len(dom_candidate_rows(initial)),
            "after_scroll_rows": max([len(dom_candidate_rows(initial))] + [int(sample["row_count"]) for sample in scroll_samples]),
            "total_rows": len(chapters),
            "all_chapter_link_count": final.get("all_chapter_link_count", 0),
            "pagination": bool(pagination_candidates),
            "pagination_candidates": pagination_candidates,
            "lazy_loading": len(chapters) > len(dom_candidate_rows(initial)),
            "virtualized": False,
            "scroll_samples": scroll_samples,
            "network_after_scroll_count": sum(int(sample.get("network_response_count_delta") or 0) for sample in scroll_samples),
            "dom_order": dom_order,
            "structured_chapter_count": len(structured),
        }
        account_indicators = final.get("login_indicators") or []
        account_context = "unknown"
        if any(re.search(r"ログアウト|sign out|マイページ|account", str(item), re.IGNORECASE) for item in account_indicators):
            account_context = "authenticated_indicator_observed"
        elif any(re.search(r"ログイン|sign in", str(item), re.IGNORECASE) for item in account_indicators):
            account_context = "login_indicator_observed"
        api_candidates = [
            {
                "url": record.get("url"),
                "method": record.get("method"),
                "status": record.get("status"),
                "resource_type": record.get("resource_type"),
                "content_type": record.get("content_type"),
                "body_bytes": record.get("body_bytes"),
                "body_sha256": record.get("body_sha256"),
                "decode_status": "json_records_extracted" if record.get("structured_record_count") else "protobuf_or_unrecognized",
            }
            for record in self.network_records
            if "chapter" in str(record.get("url") or "").lower()
        ]
        for api_index, api_record in enumerate(api_candidates):
            if "protobuf" in str(api_record.get("content_type") or "").lower() and not api_record.get("relevant_payload_path"):
                payload_path = self.output_dir / "network" / "relevant_payloads" / f"api_{api_index:03d}.json"
                write_json(
                    payload_path,
                    {
                        "source": api_record.get("url"),
                        "content_type": api_record.get("content_type"),
                        "body_bytes": api_record.get("body_bytes"),
                        "body_sha256": api_record.get("body_sha256"),
                        "body_prefix_hex": next(
                            (record.get("body_prefix_hex") for record in self.network_records if record.get("url") == api_record.get("url")),
                            None,
                        ),
                        "decode_status": "protobuf_not_decoded",
                    },
                )
                api_record["relevant_payload_path"] = str(payload_path.relative_to(self.output_dir))
        api_endpoints = sorted({str(record.get("url")) for record in api_candidates if record.get("url")})
        relevant_endpoints = sorted(set(relevant_endpoints) | set(api_endpoints))
        network = {
            "relevant_endpoints": relevant_endpoints,
            "api_candidates": api_candidates,
            "structured_api_observed": bool(api_candidates),
            "structured_data_formats": sorted({str(record.get("content_type")) for record in api_candidates if record.get("content_type")}),
            "responses": self.network_records,
            "structured_listing_found": structured_listing_found,
            "structured_chapter_count": len(structured),
            "structured_records": structured,
            "embedded_payloads": embedded,
            "dom_structured_matched_chapters": merge_result["matched_chapters"],
            "dom_structured_conflicts": merge_result["conflicting_states"],
        }
        questions = build_question_answers(listing=listing, chapters=chapters, structured=structured, frontier=frontier)
        if api_candidates and not structured:
            questions["Q9_non_DOM_structured_access"] = "API observed as protobuf; chapter fields not decoded in Z4-0"
        report = {
            "schema_version": "z4-0",
            "probe_phase": "Z4-0 research only",
            "production_discovery_adapter": "NOT YET IMPLEMENTED",
            "read_only": True,
            "target": self.target,
            "title_id": self.title_id,
            "document_title": final.get("document_title"),
            "final_url": final.get("url"),
            "account_context": account_context,
            "listing": listing,
            "chapters": chapters,
            "network": network,
            "ticket_frontier": frontier,
            "questions": questions,
            "unknowns": [
                "Ticket consumption order was not tested by design.",
                "A single account snapshot cannot prove that P is a stable ticket-eligible type.",
                "Rental origin (ticket/point/coin) remains unknown unless explicitly represented.",
            ],
            "safety": {
                "chapter_links_clicked": 0,
                "access_controls_clicked": 0,
                "ticket_consumed": False,
                "purchase_started": False,
                "rental_started": False,
                "login_performed": False,
                "advertisement_viewed": False,
                "viewer_navigation_performed": False,
            },
            "errors": self.errors,
        }
        write_json(self.output_dir / "report.json", report)
        write_json(self.output_dir / "dom" / "listing.json", {"initial": initial, "scroll_samples": scroll_samples, "final": final})
        write_json(self.output_dir / "network" / "responses.json", self.network_records)
        (self.output_dir / "summary.md").write_text(make_summary(report), encoding="utf-8")
        return report


async def run_probe(url: str, output_dir: Path, cdp_endpoint: str | None) -> dict[str, Any]:
    target = parse_target_list_url(url)
    if target is None:
        raise ValueError(
            "--url must be https://zebrack-comic.shueisha.co.jp/title/<id>/chapter/list"
        )
    session = await BrowserSession.connect(resolve_cdp_endpoint(cli_endpoint=cdp_endpoint))
    page = await session.new_page()
    probe = ZeblackDiscoveryProbe(page, output_dir, url, target["title_id"])
    try:
        return await probe.run()
    finally:
        await session.close_page(page)
        await session.close()


def main() -> None:  # pragma: no cover - live CLI entry point
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default=DEFAULT_URL)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--cdp-endpoint", default=None)
    args = parser.parse_args()
    report = asyncio.run(run_probe(args.url, args.output_dir, args.cdp_endpoint))
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
