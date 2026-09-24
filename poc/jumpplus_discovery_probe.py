"""Observation-only J0 probe for Jump+ episode discovery.

This script deliberately does not implement or register a production Discovery
adapter.  It attaches to the shared Crawler Chrome, scopes observations to the
episode tabpanel under the work information section, and only clicks controls
that are revalidated as episode-list range switches or ``もっと見る`` controls.
Episode links and all access/purchase/navigation controls are never clicked.

Example::

    .\\.venv\\Scripts\\python.exe poc\\jumpplus_discovery_probe.py `
        --url https://shonenjumpplus.com/episode/13932016480029111789 `
        --output-dir output\\jumpplus_discovery_probe
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from playwright.async_api import Page, Response
from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from screenshot_crawler.core.browser import BrowserSession, resolve_cdp_endpoint

DEFAULT_URL = "https://shonenjumpplus.com/episode/13932016480029111789"
DEFAULT_OUTPUT_DIR = Path("output/jumpplus_discovery_probe")
MAX_MORE_CLICKS = 20
WAIT_TIMEOUT_MS = 15_000
MAX_SCRIPT_TEXT = 2_000_000
MAX_RESPONSE_BODY = 2_000_000

EPISODE_PATH_RE = re.compile(r"^/episode/(?P<episode_id>[0-9]+)/?$")
DATE_RE = re.compile(
    r"(?:\d{4}[年/]\s*\d{1,2}[月/]\s*\d{1,2}日?|\d{4}-\d{1,2}-\d{1,2})"
)
RANGE_LABEL_RE = re.compile(r"^\s*(?P<first>\d+)\s*[-–—〜～]\s*(?P<last>\d+)\s*$")
EPISODE_HREF_RE = re.compile(r"/episode/[0-9]+(?:[/?#]|$)")
FORBIDDEN_TEXT_RE = re.compile(
    r"(?:購入|ポイント|レンタル|ログイン|会員登録|次の話|前の話|コメント|アプリ|広告|purchase|point|rental|login|next|previous)",
    re.IGNORECASE,
)


def extract_episode_id(url: str) -> str | None:
    """Extract an episode id from a canonical Jump+ episode URL."""

    try:
        parsed = urlparse(url)
    except ValueError:
        return None
    if (parsed.hostname or "").lower() not in {"shonenjumpplus.com", "www.shonenjumpplus.com"}:
        return None
    match = EPISODE_PATH_RE.fullmatch(parsed.path)
    return match.group("episode_id") if match else None


def parse_range_label(label: str) -> tuple[int, int] | None:
    """Parse a numeric range label without assuming any particular values."""

    match = RANGE_LABEL_RE.fullmatch(" ".join(label.split()))
    if match is None:
        return None
    return int(match.group("first")), int(match.group("last"))


def identity_signature(episodes: list[dict[str, Any]]) -> tuple[str, ...]:
    """Return an order-preserving episode identity signature."""

    return tuple(str(row["episode_id"]) for row in episodes if row.get("episode_id"))


def access_pattern(row: dict[str, Any]) -> dict[str, Any]:
    """Keep only access-display fields when grouping observed row states."""

    return {
        "access_title": row.get("access_title"),
        "access_text": row.get("access_text", []),
        "access_class": row.get("access_class", []),
        "access_icons": row.get("access_icons", []),
    }


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _json_default(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    raise TypeError(f"not JSON serializable: {type(value)!r}")


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, default=_json_default) + "\n",
        encoding="utf-8",
    )


def write_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8")


def _hash_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8", errors="replace")).hexdigest()


async def collect_scripts(page: Page) -> dict[str, Any]:
    root_data_attributes = await page.evaluate(
        """() => Object.fromEntries(
          ['html', 'body'].map(name => {
            const el = name === 'html' ? document.documentElement : document.body;
            return [name, Object.fromEntries([...el.attributes]
              .filter(a => ['data-route', 'data-media', 'data-gtm-data-layer', 'data-endpoint', 'data-root-uri']
                .includes(a.name)).map(a => [a.name, a.value]))];
          })
        )"""
    )
    scripts = await page.locator("script").evaluate_all(
        f"""els => els.map((el, index) => ({{
          index,
          type: el.getAttribute('type'),
          id: el.id || null,
          src: el.getAttribute('src'),
          dataAttributes: Object.fromEntries([...el.attributes]
            .filter(a => a.name.startsWith('data-')).map(a => [a.name, a.value])),
          text: (el.textContent || '').slice(0, {MAX_SCRIPT_TEXT}),
          length: (el.textContent || '').length
        }}))"""
    )
    application_json: list[dict[str, Any]] = []
    relevant: list[dict[str, Any]] = []
    for script in scripts:
        text = str(script.get("text") or "")
        if str(script.get("type") or "").lower() == "application/json":
            parsed: Any = None
            parse_error = None
            try:
                parsed = json.loads(text)
            except (TypeError, ValueError) as exc:
                parse_error = str(exc)
            application_json.append(
                {"index": script["index"], "id": script["id"], "length": script["length"], "parsed": parsed, "parse_error": parse_error}
            )
        if any(term in text for term in ("episode", "readableProduct", "series", "13932016480029111789")):
            relevant.append(
                {
                    "index": script["index"],
                    "id": script["id"],
                    "type": script["type"],
                    "src": script["src"],
                    "length": script["length"],
                    "containsTargetEpisodeId": "13932016480029111789" in text,
                    "containsEpisodeTerm": "episode" in text.lower(),
                    "preview": text[:4000],
                }
            )
    return {
        "count": len(scripts),
        "root_data_attributes": root_data_attributes,
        "application_json": application_json,
        "relevant": relevant,
        "scripts": scripts,
    }


async def install_network_observer(page: Page) -> tuple[list[dict[str, Any]], list[asyncio.Task[Any]]]:
    records: list[dict[str, Any]] = []
    body_tasks: list[asyncio.Task[Any]] = []

    async def capture_body(response: Response, record: dict[str, Any]) -> None:
        content_type = (response.headers.get("content-type") or "").lower()
        if response.request.resource_type not in {"xhr", "fetch", "document"} and not any(
            t in content_type for t in ("json", "html", "javascript")
        ):
            return
        try:
            body = await response.body()
        except Exception as exc:  # noqa: BLE001 - diagnostics must survive body races
            record["body_error"] = type(exc).__name__
            return
        record["body_bytes"] = len(body)
        if len(body) <= MAX_RESPONSE_BODY:
            text = body.decode("utf-8", errors="replace")
            record["body_sha256"] = _hash_text(text)
            record["body_preview"] = text[:12_000]
            if "json" in content_type:
                try:
                    record["json"] = json.loads(text)
                except ValueError:
                    record["json_parse_error"] = True

    def on_response(response: Response) -> None:
        record = {
            "timestamp": _now_iso(),
            "url": response.url,
            "status": response.status,
            "resource_type": response.request.resource_type,
            "method": response.request.method,
            "content_type": response.headers.get("content-type"),
        }
        records.append(record)
        if len(records) <= 500:
            body_tasks.append(asyncio.create_task(capture_body(response, record)))

    page.on("response", on_response)
    return records, body_tasks


async def inspect_listing(page: Page, target_episode_id: str) -> dict[str, Any]:
    return await page.evaluate(
        r"""({targetEpisodeId}) => {
          const attrs = el => Object.fromEntries([...el.attributes]
            .filter(a => a.name.startsWith('data-') || a.name.startsWith('aria-') || a.name === 'id')
            .map(a => [a.name, a.value]));
          const classes = el => [...(el?.classList || [])];
          const text = el => (el?.innerText || el?.textContent || '').replace(/\s+/g, ' ').trim();
          const cssPath = el => {
            if (!el) return null;
            if (el.id && !/[ :]/.test(el.id)) return `#${CSS.escape(el.id)}`;
            const parts = [];
            let node = el;
            while (node && node.nodeType === 1 && node !== document.body) {
              let part = node.tagName.toLowerCase();
              const stable = [...node.classList].filter(c => /(?:episode|pagination|readable|series)/i.test(c)).slice(0, 2);
              if (stable.length) part += stable.map(c => `.${CSS.escape(c)}`).join('');
              if (node.parentElement) {
                const same = [...node.parentElement.children].filter(x => x.tagName === node.tagName);
                if (same.length > 1) part += `:nth-of-type(${same.indexOf(node) + 1})`;
              }
              parts.unshift(part);
              const candidate = parts.join(' > ');
              try { if (document.querySelectorAll(candidate).length === 1) return candidate; } catch (_) {}
              node = node.parentElement;
            }
            return parts.join(' > ');
          };
          const isVisible = el => {
            if (!el) return false;
            const style = getComputedStyle(el);
            const rect = el.getBoundingClientRect();
            return style.display !== 'none' && style.visibility !== 'hidden' && style.opacity !== '0' && rect.width > 0 && rect.height > 0;
          };
          const episodeId = href => {
            try {
              const path = new URL(href, location.href).pathname;
              return path.match(/^\/episode\/([0-9]+)\/?$/)?.[1] || null;
            } catch (_) { return null; }
          };
          const tab = document.querySelector('[role="tab"][data-key="episode"]') ||
            [...document.querySelectorAll('[role="tab"]')].find(el => text(el).includes('話の一覧'));
          const panelId = tab?.getAttribute('aria-controls');
          const panel = (panelId && document.getElementById(panelId)) ||
            tab?.parentElement?.parentElement?.querySelector('[role="tabpanel"]');
          const workSection = tab?.closest('section.series-information.type-episode') ||
            tab?.closest('section') || null;
          const lists = panel ? [...panel.querySelectorAll('ul')].filter(ul =>
            [...ul.classList].some(c => /series-episode-list/i.test(c)) ||
            [...ul.querySelectorAll('a[href]')].some(a => episodeId(a.href))
          ) : [];
          const list = lists[0] || null;
          const rowElements = list ? [...list.children].filter(li => [...li.querySelectorAll('a[href]')].some(a => episodeId(a.href))) : [];
          const allEpisodeLinks = panel ? [...panel.querySelectorAll('a[href]')].filter(a => episodeId(a.href)) : [];
          const extractAccess = row => {
            const all = [...row.querySelectorAll('*')];
            const accessEls = all.filter(el => {
              const label = `${text(el)} ${classes(el).join(' ')}`.toLowerCase();
              return /free|point|rent|purchase|paid|lock|ticket|無料|ポイント|レンタル|購入|読める|公開終了|期限/.test(label);
            }).filter(el => text(el) || classes(el).length);
            const icons = [...row.querySelectorAll('img, svg, i, use')].map(el => ({tag: el.tagName.toLowerCase(), text: text(el), class: classes(el), attrs: attrs(el)}));
            return {
              visibleText: [...new Set(accessEls.filter(isVisible).map(text).filter(Boolean))],
              classes: [...new Set(accessEls.flatMap(classes))],
              data: accessEls.map(attrs),
              icons
            };
          };
          const dateFromText = value => value.match(/(?:\d{4}[年\/]\s*\d{1,2}[月\/]\s*\d{1,2}日?|\d{4}-\d{1,2}-\d{1,2})/)?.[0] || null;
          const rows = rowElements.map((row, index) => {
            const links = [...row.querySelectorAll('a[href]')];
            const episodeLink = links.find(a => episodeId(a.href));
            const rowText = text(row);
            const descendants = [...row.querySelectorAll('*')].filter(isVisible);
            const dated = descendants.map(text).map(dateFromText).find(Boolean) || dateFromText(rowText);
            const titleNodes = descendants.filter(el => /title|ttl|episode/i.test(classes(el).join(' ')) && text(el));
            const access = extractAccess(row);
            const orderMatch = rowText.match(/(?:第\s*)?[0-9０-９]+(?:\s*話|\s*回)?/);
            return {
              index,
              href: episodeLink?.href || null,
              episode_id: episodeLink ? episodeId(episodeLink.href) : null,
              anchor_count: links.length,
              text: rowText,
              classes: classes(row),
              data_attributes: attrs(row),
              order_text: orderMatch?.[0] || null,
              title_text: titleNodes.length ? [...new Set(titleNodes.map(text))].join(' | ') : null,
              published_text: dated,
              access_text: access.visibleText,
              access_class: access.classes,
              access_icons: access.icons,
              access_data: access.data,
              descendant_summary: descendants.slice(0, 40).map(el => ({tag: el.tagName.toLowerCase(), class: classes(el), text: text(el), data: attrs(el)})),
              links: links.map(a => ({href: a.href, text: text(a), classes: classes(a), data: attrs(a)}))
            };
          });
          const controls = panel ? [...panel.querySelectorAll('button, a, [role="button"], [role="tab"]')].map((el, index) => ({
            index,
            tag: el.tagName.toLowerCase(),
            href: el.href || null,
            text: text(el),
            visible: isVisible(el),
            disabled: !!el.disabled || el.getAttribute('aria-disabled') === 'true',
            selected: el.getAttribute('aria-selected') || el.getAttribute('data-selected') || null,
            current: el.getAttribute('aria-current') || null,
            classes: classes(el),
            data_attributes: attrs(el),
            selector: cssPath(el),
            is_episode_link: !!episodeId(el.href || ''),
            is_more_candidate: text(el).includes('もっと見る') && !el.closest('#episode-comment,.series-comment-contents'),
            is_range_candidate: !!text(el).match(/^\s*\d+\s*[-–—〜～]\s*\d+\s*$/)
          })).filter(x => x.visible || x.text);
          const rangeControls = controls.filter(x => x.is_range_candidate && !x.is_episode_link);
          const moreControls = controls.filter(x => x.is_more_candidate && !x.is_episode_link);
          const panelHtml = panel?.innerHTML || '';
          const visibleRows = rowElements.filter(isVisible).length;
          const allRows = list ? [...list.children].length : 0;
          const workLinks = workSection ? [...workSection.querySelectorAll('a[href]')].map(a => ({href: a.href, text: text(a), classes: classes(a), data: attrs(a)})) : [];
          const workData = workSection ? {
            selector: cssPath(workSection),
            tag: workSection.tagName.toLowerCase(),
            classes: classes(workSection),
            data_attributes: attrs(workSection),
            title: text(workSection.querySelector('h1.series-header-title, [class*="series-header-title"]')) || null,
            author: text(workSection.querySelector('h2.series-header-author, [class*="series-header-author"]')) || null,
            links: workLinks
          } : null;
          return {
            captured_at: new Date().toISOString(),
            url: location.href,
            target_episode_id: targetEpisodeId,
            tab: tab ? {tag: tab.tagName.toLowerCase(), text: text(tab), classes: classes(tab), data_attributes: attrs(tab), selector: cssPath(tab)} : null,
            scope: panel ? {selector: cssPath(panel), tag: panel.tagName.toLowerCase(), id: panel.id || null, classes: classes(panel), data_attributes: attrs(panel), aria_labelledby: panel.getAttribute('aria-labelledby'), parent: panel.parentElement ? {tag: panel.parentElement.tagName.toLowerCase(), classes: classes(panel.parentElement), data_attributes: attrs(panel.parentElement)} : null} : null,
            listing_container: list ? {selector: cssPath(list), tag: list.tagName.toLowerCase(), classes: classes(list), data_attributes: attrs(list), parent: list.parentElement ? {tag: list.parentElement.tagName.toLowerCase(), classes: classes(list.parentElement), data_attributes: attrs(list.parentElement)} : null, all_child_count: allRows, visible_child_count: visibleRows } : null,
            work: workData,
            episode_anchor_count: allEpisodeLinks.length,
            episodes: rows,
            range_controls: rangeControls,
            more_controls: moreControls,
            controls,
            current_episode_in_rows: rows.some(row => row.episode_id === targetEpisodeId),
            panel_text: text(panel),
            panel_html_length: panelHtml.length,
            panel_html_hash: panelHtml ? Array.from(new TextEncoder().encode(panelHtml)).reduce((h, c) => (h * 31 + c) >>> 0, 0).toString(16) : null
          };
        }""",
        {"targetEpisodeId": target_episode_id},
    )


def remove_js_placeholder(value: Any) -> Any:
    """Remove the intentionally browser-only placeholder if returned."""

    if isinstance(value, dict):
        return {k: remove_js_placeholder(v) for k, v in value.items() if k != "_"}
    if isinstance(value, list):
        return [remove_js_placeholder(v) for v in value]
    return value


async def inspect_listing_live(page: Page, target_episode_id: str) -> dict[str, Any]:
    """Inspect the live episode tabpanel with deliberately small browser JS."""

    return await page.evaluate(
        r"""({targetEpisodeId}) => {
          function text(el) {
            return el ? (el.innerText || el.textContent || '').replace(/\s+/g, ' ').trim() : '';
          }
          function classes(el) {
            return el ? Array.from(el.classList) : [];
          }
          function attributes(el) {
            return Object.fromEntries(Array.from(el.attributes)
              .filter(a => a.name.indexOf('data-') === 0 || a.name.indexOf('aria-') === 0 || a.name === 'id')
              .map(a => [a.name, a.value]));
          }
          function episodeId(href) {
            if (!href) return null;
            try {
              const path = new URL(href, location.href).pathname;
              const match = path.match(/^\/episode\/([0-9]+)\/?$/);
              return match ? match[1] : null;
            } catch (error) {
              return null;
            }
          }
          function visible(el) {
            if (!el) return false;
            const style = getComputedStyle(el);
            const rect = el.getBoundingClientRect();
            return style.display !== 'none' && style.visibility !== 'hidden' && rect.width > 0 && rect.height > 0;
          }
          function selectorFor(el) {
            if (!el) return null;
            if (el.id) return '#' + CSS.escape(el.id);
            const parts = [];
            let node = el;
            while (node && node.nodeType === 1 && node !== document.body) {
              let part = node.tagName.toLowerCase();
              const stable = Array.from(node.classList).filter(c => /episode|pagination|series|readable/i.test(c)).slice(0, 1);
              if (stable.length) part += '.' + CSS.escape(stable[0]);
              const parent = node.parentElement;
              if (parent) {
                const same = Array.from(parent.children).filter(x => x.tagName === node.tagName);
                if (same.length > 1) part += ':nth-of-type(' + (same.indexOf(node) + 1) + ')';
              }
              parts.unshift(part);
              const candidate = parts.join(' > ');
              try {
                if (document.querySelectorAll(candidate).length === 1) return candidate;
              } catch (error) {}
              node = parent;
            }
            return parts.join(' > ');
          }
          const tab = document.querySelector('[role="tab"][data-key="episode"]') ||
            Array.from(document.querySelectorAll('[role="tab"]')).find(el => text(el).indexOf('話の一覧') >= 0);
          const panelId = tab ? tab.getAttribute('aria-controls') : null;
          const panel = (panelId ? document.getElementById(panelId) : null) ||
            (tab && tab.parentElement && tab.parentElement.parentElement ? tab.parentElement.parentElement.querySelector('[role="tabpanel"]') : null);
          const section = tab ? (tab.closest('section.series-information.type-episode') || tab.closest('section')) : null;
          const lists = panel ? Array.from(panel.querySelectorAll('ul')).filter(ul =>
            Array.from(ul.classList).some(c => /series-episode-list/i.test(c)) ||
            Array.from(ul.querySelectorAll('a[href]')).some(a => episodeId(a.href))
          ) : [];
          const list = lists[0] || null;
          const rowElements = list ? Array.from(list.children).filter(li =>
            Array.from(li.querySelectorAll('a[href]')).some(a => episodeId(a.href)) ||
            li.classList.contains('index-module--current-readable-product--HKk5y') ||
            li.classList.toString().indexOf('current-readable-product') >= 0
          ) : [];
          const rows = rowElements.map((row, index) => {
            const links = Array.from(row.querySelectorAll('a[href]'));
            const link = links.find(a => episodeId(a.href));
            const isCurrent = row.classList.toString().indexOf('current-readable-product') >= 0;
            const rowText = text(row);
            const date = rowText.match(/(?:\d{4}[年\/]\s*\d{1,2}[月\/]\s*\d{1,2}日?|\d{4}-\d{1,2}-\d{1,2})/);
            const order = rowText.match(/(?:第\s*)?[0-9０-９]+(?:\s*話|\s*回)?/);
            const orderAfterDate = date ? rowText.slice(date[0].length).match(/^\s*([0-9]+)/) : null;
            const accessElements = Array.from(row.querySelectorAll('[class*="series-episode-list-price"], [class*="series-episode-list-is-free"], [class*="rental-point"], [class*="rental-term"]')).filter(el => {
              const label = (text(el) + ' ' + classes(el).join(' ')).toLowerCase();
              return /free|point|rent|purchase|paid|lock|ticket|無料|ポイント|レンタル|購入|読める|公開終了|期限/.test(label);
            });
            return {
              index,
              href: link ? link.href : null,
              episode_id: link ? episodeId(link.href) : (isCurrent ? targetEpisodeId : null),
              anchor_count: links.length,
              text: rowText,
              classes: classes(row),
              data_attributes: attributes(row),
              order_text: orderAfterDate ? orderAfterDate[1] : (order ? order[0] : null),
              title_text: Array.from(row.querySelectorAll('[class*="title"],[class*="ttl"],h3,h4')).map(text).filter(Boolean).join(' | ') || null,
              published_text: date ? date[0] : null,
              access_text: Array.from(new Set(accessElements.filter(visible).map(text).filter(Boolean))),
              access_title: (row.querySelector('[class*="series-episode-list-price"]') || {}).getAttribute?.('title') || null,
              access_class: Array.from(new Set(accessElements.flatMap(classes))),
              access_icons: Array.from(row.querySelectorAll('img,svg,i,use')).map(el => ({tag: el.tagName.toLowerCase(), text: text(el), classes: classes(el), data: attributes(el)})),
              access_data: accessElements.map(attributes),
              links: links.map(a => ({href: a.href, text: text(a), classes: classes(a), data: attributes(a)}))
            };
          });
          const controls = panel ? Array.from(panel.querySelectorAll('button,a,[role="button"],[role="tab"]')).map((el, index) => {
            const label = text(el);
            return {
              index, tag: el.tagName.toLowerCase(), href: el.href || null, text: label, visible: visible(el),
              disabled: !!el.disabled || el.getAttribute('aria-disabled') === 'true',
              selected: el.getAttribute('aria-selected') || el.getAttribute('data-selected') || null,
              current: el.getAttribute('aria-current') || null, classes: classes(el),
              data_attributes: attributes(el), selector: selectorFor(el),
              is_episode_link: !!episodeId(el.href || ''),
              is_more_candidate: label.indexOf('もっと見る') >= 0 && !el.closest('#episode-comment,.series-comment-contents'),
              is_range_candidate: /^\s*\d+\s*[-–—〜～]\s*\d+\s*$/.test(label)
            };
          }).filter(x => x.visible || x.text) : [];
          const rangeControls = controls.filter(x => x.is_range_candidate && !x.is_episode_link);
          const moreControls = controls.filter(x => x.is_more_candidate && !x.is_episode_link);
          const sectionLinks = section ? Array.from(section.querySelectorAll('a[href]')).filter(a => !episodeId(a.href)).map(a => ({
            href: a.href, text: text(a), classes: classes(a), data: attributes(a)
          })) : [];
          const panelHtml = panel ? panel.innerHTML : '';
          return {
            captured_at: new Date().toISOString(), url: location.href, target_episode_id: targetEpisodeId,
            tab: tab ? {tag: tab.tagName.toLowerCase(), text: text(tab), classes: classes(tab), data_attributes: attributes(tab), selector: selectorFor(tab)} : null,
            scope: panel ? {selector: selectorFor(panel), tag: panel.tagName.toLowerCase(), id: panel.id || null, classes: classes(panel), data_attributes: attributes(panel), aria_labelledby: panel.getAttribute('aria-labelledby')} : null,
            listing_container: list ? {selector: selectorFor(list), tag: list.tagName.toLowerCase(), classes: classes(list), data_attributes: attributes(list), all_child_count: list.children.length, visible_child_count: rowElements.filter(visible).length} : null,
            work: section ? {selector: selectorFor(section), tag: section.tagName.toLowerCase(), classes: classes(section), data_attributes: attributes(section), title: text(section.querySelector('h1.series-header-title,[class*="series-header-title"]')) || null, author: text(section.querySelector('h2.series-header-author,[class*="series-header-author"]')) || null, links: sectionLinks} : null,
            episode_anchor_count: panel ? Array.from(panel.querySelectorAll('a[href]')).filter(a => episodeId(a.href)).length : 0,
            episodes: rows, range_controls: rangeControls, more_controls: moreControls, controls,
            current_episode_in_rows: rows.some(row => row.episode_id === targetEpisodeId),
            panel_text: text(panel), panel_html_length: panelHtml.length,
            panel_html_hash: panelHtml ? Array.from(new TextEncoder().encode(panelHtml)).reduce((h, c) => (h * 31 + c) >>> 0, 0).toString(16) : null
          };
        }""",
        {"targetEpisodeId": target_episode_id},
    )


async def wait_for_listing(page: Page, target_episode_id: str) -> dict[str, Any]:
    last: dict[str, Any] | None = None
    # The episode panel is lazy-mounted below the viewer on a fresh load.
    # Scrolling the already identified work section into view is passive
    # readiness handling; it does not activate a site control.
    work_section = page.locator("section.series-information.type-episode")
    if await work_section.count():
        await page.locator("section.series-information.type-episode").scroll_into_view_if_needed()
    for _ in range(80):
        last = remove_js_placeholder(await inspect_listing_live(page, target_episode_id))
        if last.get("scope") and last.get("episodes"):
            return last
        await page.wait_for_timeout(250)
    raise RuntimeError(f"Jump+ episode listing did not become observable: {last}")


async def wait_for_network_idle(page: Page) -> bool:
    try:
        await page.wait_for_load_state("networkidle", timeout=WAIT_TIMEOUT_MS)
    except PlaywrightTimeoutError:
        return False
    return True


def episode_ids(observation: dict[str, Any]) -> list[str]:
    return [str(row["episode_id"]) for row in observation.get("episodes", []) if row.get("episode_id")]


async def revalidate_and_click_more(page: Page, target_episode_id: str) -> dict[str, Any] | None:
    observation = remove_js_placeholder(await inspect_listing_live(page, target_episode_id))
    candidates = [x for x in observation.get("more_controls", []) if x.get("visible") and not x.get("disabled")]
    if len(candidates) != 1:
        return {"status": "not_unique", "candidates": candidates}
    candidate = candidates[0]
    if candidate.get("is_episode_link") or FORBIDDEN_TEXT_RE.search(str(candidate.get("text") or "")):
        return {"status": "rejected_forbidden", "candidate": candidate}
    locator = page.locator(str(candidate["selector"]))
    if await locator.count() != 1:
        return {"status": "selector_not_unique", "candidate": candidate}
    before_url = page.url
    await locator.scroll_into_view_if_needed()
    await locator.click(timeout=WAIT_TIMEOUT_MS, no_wait_after=True)
    for _ in range(40):
        await page.wait_for_timeout(250)
        current = remove_js_placeholder(await inspect_listing_live(page, target_episode_id))
        if page.url != before_url:
            return {"status": "navigation_changed", "before_url": before_url, "after_url": page.url, "candidate": candidate}
        if len(set(episode_ids(current))) > len(set(episode_ids(observation))):
            return {"status": "progress", "candidate": candidate, "before": observation, "after": current}
    current = remove_js_placeholder(await inspect_listing_live(page, target_episode_id))
    return {"status": "no_progress", "candidate": candidate, "before": observation, "after": current}


async def expand_current_range(page: Page, target_episode_id: str, output_dir: Path) -> dict[str, Any]:
    before = remove_js_placeholder(await inspect_listing_live(page, target_episode_id))
    range_dir = output_dir
    write_json(range_dir / "before.json", before)
    await page.screenshot(path=str(range_dir / "before.png"), full_page=False)
    initial_ids = set(episode_ids(before))
    clicks: list[dict[str, Any]] = []
    incomplete = False
    for click_number in range(1, MAX_MORE_CLICKS + 1):
        result = await revalidate_and_click_more(page, target_episode_id)
        clicks.append({"click_number": click_number, **(result or {"status": "none"})})
        if not result or result.get("status") == "not_unique":
            break
        if result.get("status") == "progress":
            continue
        incomplete = True
        break
    after = remove_js_placeholder(await inspect_listing_live(page, target_episode_id))
    final_ids = set(episode_ids(after))
    if len(final_ids) < len(initial_ids):
        incomplete = True
    write_json(range_dir / "expanded.json", after)
    write_json(range_dir / "more_clicks.json", clicks)
    await page.screenshot(path=str(range_dir / "expanded.png"), full_page=False)
    return {
        "initial_episode_count": len(initial_ids),
        "initial_episode_ids": list(initial_ids),
        "more_click_count": sum(1 for c in clicks if c.get("status") == "progress"),
        "click_attempt_count": len(clicks),
        "final_episode_count": len(final_ids),
        "incomplete": incomplete,
        "clicks": clicks,
        "before_url": before.get("url"),
        "after_url": after.get("url"),
        "before_identity_signature": list(identity_signature(before.get("episodes", []))),
        "after_identity_signature": list(identity_signature(after.get("episodes", []))),
        "observation": after,
    }


async def run_probe(url: str, output_dir: Path, cdp_endpoint: str | None) -> dict[str, Any]:
    target_episode_id = extract_episode_id(url)
    if target_episode_id is None:
        raise ValueError("--url must be a canonical Jump+ /episode/<id> URL")
    output_dir.mkdir(parents=True, exist_ok=True)
    session = await BrowserSession.connect(resolve_cdp_endpoint(cli_endpoint=cdp_endpoint))
    page = None
    owns_page = False
    for candidate_page in session.context.pages:
        if candidate_page.url != url:
            continue
        if candidate_page.is_closed():
            continue
        candidate_observation = remove_js_placeholder(
            await inspect_listing_live(candidate_page, target_episode_id)
        )
        if candidate_observation.get("episodes"):
            page = candidate_page
            break
    if page is None:
        page = await session.new_page()
        owns_page = True
    network_records, network_tasks = await install_network_observer(page)
    range_results: list[dict[str, Any]] = []
    visited_ranges: set[str] = set()
    try:
        if owns_page:
            await page.goto(url, wait_until="domcontentloaded", timeout=WAIT_TIMEOUT_MS)
            await wait_for_network_idle(page)
        else:
            # Reused shared tabs may have been left after a previous probe run.
            # Reload to measure the page's initial selected range, not that state.
            await page.reload(wait_until="domcontentloaded", timeout=WAIT_TIMEOUT_MS)
            await wait_for_network_idle(page)
        baseline_resources = await page.evaluate(
            """() => performance.getEntriesByType('resource').map(entry => ({
              timestamp: entry.startTime,
              url: entry.name,
              initiator_type: entry.initiatorType,
              duration: entry.duration,
              transfer_size: entry.transferSize
            }))"""
        )
        network_records.extend(
            {
                "timestamp": _now_iso(),
                "url": resource.get("url"),
                "resource_type": resource.get("initiator_type"),
                "observation": "performance_baseline",
                "duration": resource.get("duration"),
                "transfer_size": resource.get("transfer_size"),
            }
            for resource in baseline_resources
        )
        initial = await wait_for_listing(page, target_episode_id)
        write_text(output_dir / "initial" / "page.html", await page.content())
        write_json(output_dir / "initial" / "listing.json", initial)
        write_json(output_dir / "initial" / "controls.json", {"controls": initial.get("controls"), "range_controls": initial.get("range_controls"), "more_controls": initial.get("more_controls")})
        write_json(output_dir / "initial" / "scripts.json", await collect_scripts(page))
        await page.screenshot(path=str(output_dir / "initial" / "screenshot.png"), full_page=False)

        initial_range_controls = initial.get("range_controls", [])
        initial_selected = next((c for c in initial_range_controls if c.get("selected") in {"true", ""} or c.get("current")), None)
        if initial_selected is None and initial_range_controls:
            initial_selected = initial_range_controls[0]

        selected_index = next(
            (index for index, control in enumerate(initial_range_controls)
             if control.get("selector") == (initial_selected or {}).get("selector")),
            None,
        )
        range_indices = list(range(len(initial_range_controls)))
        if selected_index is not None:
            range_indices.remove(selected_index)
            range_indices.insert(0, selected_index)

        for range_index in range_indices:
            current = remove_js_placeholder(await inspect_listing_live(page, target_episode_id))
            controls = current.get("range_controls", [])
            if range_index >= len(controls):
                break
            candidate = controls[range_index]
            label = str(candidate.get("text") or "")
            range_key = f"{range_index}:{label}:{candidate.get('selector')}"
            if range_key in visited_ranges:
                continue
            visited_ranges.add(range_key)
            if candidate.get("is_episode_link") or FORBIDDEN_TEXT_RE.search(label):
                range_results.append({"index": range_index, "label": label, "status": "rejected_forbidden", "control": candidate})
                continue
            selector = candidate.get("selector")
            if not selector:
                range_results.append({"index": range_index, "label": label, "status": "missing_selector", "control": candidate})
                continue
            locator = page.locator(selector)
            if await locator.count() != 1:
                range_results.append({"index": range_index, "label": label, "status": "selector_not_unique", "control": candidate})
                continue
            before_url = page.url
            network_start_index = len(network_records)
            await locator.scroll_into_view_if_needed()
            before_click = remove_js_placeholder(await inspect_listing_live(page, target_episode_id))
            if selected_index == range_index:
                # Measure the initial selected range before any tab click so a
                # collapsed "more" list is not accidentally reset by a tab
                # activation.
                after_click = before_click
            else:
                await locator.click(timeout=WAIT_TIMEOUT_MS, no_wait_after=True)
                await page.wait_for_timeout(500)
                after_click = remove_js_placeholder(await inspect_listing_live(page, target_episode_id))
            if page.url != before_url or extract_episode_id(page.url) != target_episode_id:
                raise RuntimeError(f"Range click changed target URL: {before_url} -> {page.url}")
            range_dir = output_dir / f"range_{range_index:03d}"
            result = await expand_current_range(page, target_episode_id, range_dir)
            result.update(
                {
                    "index": range_index,
                    "label": label,
                    "parsed_label": parse_range_label(label),
                    "control": candidate,
                    "before_click": before_click,
                    "after_click": after_click,
                    "network_start_index": network_start_index,
                    "network_end_index": len(network_records),
                    "url_after_click": page.url,
                }
            )
            range_results.append(result)
            write_json(range_dir / "network.json", network_records[network_start_index:])

        # If no range controls exist, still expand the single visible scope.
        if not initial_range_controls:
            result = await expand_current_range(page, target_episode_id, output_dir / "range_000")
            result.update({"index": 0, "label": None, "parsed_label": None, "control": None})
            range_results.append(result)
            write_json(output_dir / "range_000" / "network.json", network_records)

        await asyncio.gather(*network_tasks, return_exceptions=True)
        write_json(output_dir / "initial" / "network.json", network_records)
        final_observations = [r.get("observation", {}) for r in range_results]
        all_rows = [row for observation in final_observations for row in observation.get("episodes", [])]
        by_id: dict[str, list[dict[str, Any]]] = {}
        for row in all_rows:
            if row.get("episode_id"):
                by_id.setdefault(str(row["episode_id"]), []).append(row)
        duplicates = sorted({episode_id for episode_id, rows in by_id.items() if len(rows) > 1})
        distinct_access: dict[str, dict[str, Any]] = {}
        for row in all_rows:
            pattern = access_pattern(row)
            key = json.dumps(pattern, ensure_ascii=False, sort_keys=True)
            distinct_access.setdefault(key, {**pattern, "sample_episode_ids": []})
            if len(distinct_access[key]["sample_episode_ids"]) < 10 and row.get("episode_id"):
                distinct_access[key]["sample_episode_ids"].append(row["episode_id"])
        scripts = await collect_scripts(page)
        final = remove_js_placeholder(await inspect_listing_live(page, target_episode_id))
        work = initial.get("work") or {}
        label_bounds = [r.get("parsed_label") for r in range_results if r.get("parsed_label")]
        latest_range_index = None
        if label_bounds:
            latest_range_index = max(
                (r for r in range_results if r.get("parsed_label")),
                key=lambda r: max(r["parsed_label"]),
            ).get("index")
        range_report = sorted(
            ({k: v for k, v in r.items() if k != "observation"} for r in range_results),
            key=lambda item: item.get("index", -1),
        )
        gtm_data_layer: Any = None
        raw_gtm_data_layer = (
            scripts.get("root_data_attributes", {}).get("html", {}).get("data-gtm-data-layer")
        )
        if raw_gtm_data_layer:
            try:
                gtm_data_layer = json.loads(raw_gtm_data_layer)
            except json.JSONDecodeError:
                gtm_data_layer = {"raw": raw_gtm_data_layer, "parse_error": True}
        report = {
            "observed_at": _now_iso(),
            "target_url": url,
            "target_episode_id": target_episode_id,
            "final_url": page.url,
            "work": work,
            "initial_range": {"control": initial_selected, "initial_episode_count": len(episode_ids(initial)), "initial_episode_ids": episode_ids(initial)},
            "ranges": range_report,
            "episodes": list(by_id.values()),
            "unique_episode_count": len(by_id),
            "observed_row_count_across_ranges": len(all_rows),
            "duplicate_episode_ids": duplicates,
            "distinct_access_states": list(distinct_access.values()),
            "embedded_data": {
                "application_json_count": len(scripts.get("application_json", [])),
                "application_json": scripts.get("application_json", []),
                "relevant_script_candidates": scripts.get("relevant", []),
                "root_data_attributes": scripts.get("root_data_attributes", {}),
                "gtm_data_layer": gtm_data_layer,
                "series_ids_seen_in_dom": [work.get("data_attributes", {})],
            },
            "network_observation": {
                "record_count": len(network_records),
                "additional_after_initial_load": [r for r in network_records if r.get("resource_type") in {"xhr", "fetch"}],
                "json_or_html_bodies": [r for r in network_records if r.get("body_preview") is not None],
            },
            "dom_mutation_observation": {
                "initial_scope": initial.get("scope"),
                "initial_listing_container": initial.get("listing_container"),
                "final_listing_container": final.get("listing_container"),
                "range_observations": [
                    {
                        "index": r.get("index"),
                        "label": r.get("label"),
                        "before_child_count": (r.get("before_click") or {}).get("listing_container", {}).get("all_child_count"),
                        "after_child_count": (r.get("after_click") or {}).get("listing_container", {}).get("all_child_count"),
                        "before_html_hash": (r.get("before_click") or {}).get("listing_container", {}).get("html_sha256"),
                        "after_html_hash": (r.get("after_click") or {}).get("listing_container", {}).get("html_sha256"),
                    }
                    for r in range_results
                ],
            },
            "ordering": {
                "range_dom_order": [{"index": r.get("index"), "label": r.get("label"), "parsed_label": r.get("parsed_label")} for r in range_report],
                "latest_range_candidate_by_numeric_label": latest_range_index,
                "range_order_requires_inference": True,
                "episode_rows_by_range": [
                    {"index": r.get("index"), "label": r.get("label"), "episode_ids": r.get("after_identity_signature", [])}
                    for r in range_report
                ],
            },
            "facts": [
                "The probe did not register a JumpPlus Discovery adapter or modify the Discovery registry.",
                "All clicked controls were revalidated inside the episode tabpanel; episode links and access controls were not clicked.",
                f"The sample target episode id is {target_episode_id} and was kept as the URL target throughout the probe.",
            ],
            "inferences": [
                "A production adapter should treat the watchlist target as the scope authority unless a stable work identity is confirmed in the listing DOM or structured data.",
                "Full discovery should visit every observed range, expand each range until identity growth stops, and deduplicate by episode_id before yielding.",
                "Incremental discovery must choose the latest range from range metadata/order, not from the initially selected range on a target episode page.",
                "Unrecognized access state should remain unknown; this J0 does not implement a mapping function.",
            ],
            "unknowns": [
                "Whether every published Jump+ work uses the same tabpanel/range DOM shape.",
                "Whether nonnumeric or special-episode labels need an order_key policy.",
                "Whether a logged-in or time-limited access state differs from the anonymous sample.",
            ],
        }
        write_json(output_dir / "report.json", report)
        return report
    finally:
        if owns_page:
            await session.close_page(page)
        await session.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default=DEFAULT_URL)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--cdp-endpoint", default=None)
    args = parser.parse_args()
    report = asyncio.run(run_probe(args.url, args.output_dir, args.cdp_endpoint))
    print(f"Probe saved to {args.output_dir}")
    print(f"Unique episodes: {report['unique_episode_count']}")
    print(f"Ranges: {len(report['ranges'])}; duplicates: {len(report['duplicate_episode_ids'])}")


if __name__ == "__main__":
    main()
