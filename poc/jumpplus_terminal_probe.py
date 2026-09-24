r"""Read-only terminal-state probe for the Shonen Jump+ viewer.

This probe deliberately imports the production adapter only to exercise the
same viewer observation and transition methods.  It is never imported by
production code and does not change the adapter.  The only controls it clicks
are the validated viewer forward controls used by ``JumpPlusAdapter.go_next``;
it never clicks purchase, point, rental, ticket, login, or next-episode links.

Example::

    .\.venv\Scripts\python.exe poc\jumpplus_terminal_probe.py `
      --output-dir output\jumpplus_terminal_probe
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import re
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from screenshot_crawler.core.browser import BrowserSession, resolve_cdp_endpoint
from screenshot_crawler.core.fingerprint import fingerprint_bytes
from screenshot_crawler.core.state import PageState
from screenshot_crawler.site_adapters.jumpplus.adapter import JumpPlusAdapter

DEFAULT_OUTPUT_DIR = Path("output/jumpplus_terminal_probe")
DEFAULT_NORMAL_URL = "https://shonenjumpplus.com/episode/13932016480029111789"
DEFAULT_FREE_URL = "https://shonenjumpplus.com/episode/9253191256637716604"
DEFAULT_MANUAL_URL = "https://shonenjumpplus.com/episode/9253191254350319886"
MAX_TRANSITIONS = 300
SAMPLE_POINTS_MS = (100, 300, 1_000, 3_000)
EPISODE_PATH = re.compile(r"^/episode/(?P<episode_id>[0-9]+)/?$")
TERMINAL_TERMS = (
    "end",
    "finish",
    "最後",
    "次の話",
    "次話",
    "次のエピソード",
    "作品ページへ",
    "感想",
    "コメント",
    "おすすめ",
)


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, default=str) + "\n",
        encoding="utf-8",
    )


def episode_id_from_url(url: str) -> str:
    parsed = urlparse(url)
    match = EPISODE_PATH.fullmatch(parsed.path)
    if parsed.hostname not in {"shonenjumpplus.com", "www.shonenjumpplus.com"} or not match:
        raise ValueError(f"not a canonical Jump+ episode URL: {url}")
    return match.group("episode_id")


def page_state_value(value: Any) -> str:
    return value.value if isinstance(value, PageState) else str(value)


async def visible_control(locator: Any) -> dict[str, Any]:
    return await locator.evaluate(
        """element => {
          const rect = element.getBoundingClientRect();
          const style = getComputedStyle(element);
          const inViewport = rect.bottom > 0 && rect.right > 0 &&
            rect.left < innerWidth && rect.top < innerHeight;
          const attrs = {};
          for (const attr of element.attributes) attrs[attr.name] = attr.value;
          return {
            tag: element.tagName.toLowerCase(),
            text: (element.innerText || '').trim(),
            aria_label: element.getAttribute('aria-label'),
            title: element.getAttribute('title'),
            href: element.getAttribute('href'),
            class: element.getAttribute('class'),
            disabled: element.hasAttribute('disabled'),
            aria_disabled: element.getAttribute('aria-disabled'),
            attributes: attrs,
            visible: rect.width > 0 && rect.height > 0 && style.display !== 'none',
            in_viewport: inViewport,
            bounding_rect: {x: rect.x, y: rect.y, width: rect.width, height: rect.height},
          };
        }"""
    )


async def dom_snapshot(page: Any) -> dict[str, Any]:
    return await page.evaluate(
        """terms => {
          const visible = element => {
            if (!element) return false;
            const rect = element.getBoundingClientRect();
            const style = getComputedStyle(element);
            return rect.width > 0 && rect.height > 0 && style.display !== 'none' &&
              style.visibility !== 'hidden';
          };
          const inViewport = element => {
            if (!element) return false;
            const rect = element.getBoundingClientRect();
            return visible(element) && rect.bottom > 0 && rect.right > 0 &&
              rect.left < innerWidth && rect.top < innerHeight;
          };
          const attrs = element => {
            const result = {};
            for (const attr of element.attributes) result[attr.name] = attr.value;
            return result;
          };
          const rect = element => {
            const value = element.getBoundingClientRect();
            return {x: value.x, y: value.y, width: value.width, height: value.height};
          };
          const viewer = document.querySelector('section.viewer.js-viewer');
          const areaRoot = viewer?.querySelector('.image-container.js-viewer-content');
          const areas = [...(areaRoot?.querySelectorAll('.page-area.js-page-area') || [])]
            .map((element, index) => ({
              dom_index: index,
              tag: element.tagName.toLowerCase(),
              class: element.getAttribute('class'),
              data: attrs(element),
              aria: Object.fromEntries([...element.attributes]
                .filter(item => item.name.startsWith('aria-'))
                .map(item => [item.name, item.value])),
              visible: visible(element),
              in_viewport: inViewport(element),
              bounding_rect: rect(element),
              canvas_count: element.querySelectorAll('canvas').length,
              link_count: element.querySelectorAll('a[href]').length,
              canvases: [...element.querySelectorAll('canvas')].map(canvas => ({
                id: canvas.id || null,
                class: canvas.getAttribute('class'),
                width: canvas.width,
                height: canvas.height,
                visible: visible(canvas),
                in_viewport: inViewport(canvas),
              })),
              links: [...element.querySelectorAll('a[href]')].map(link => ({
                href: link.href,
                text: (link.innerText || '').trim(),
                class: link.getAttribute('class'),
                visible: visible(link),
                in_viewport: inViewport(link),
              })),
            }));
          const terminal_nodes = [];
          const candidates = [...document.querySelectorAll('body *')];
          for (const element of candidates) {
            const text = (element.innerText || '').replace(/\\s+/g, ' ').trim();
            if (!text || text.length > 200) continue;
            const lowered = text.toLowerCase();
            const matched = terms.filter(term => lowered.includes(term.toLowerCase()));
            if (!matched.length) continue;
            terminal_nodes.push({
              text,
              matched_terms: matched,
              tag: element.tagName.toLowerCase(),
              class: element.getAttribute('class'),
              href: element.getAttribute('href'),
              aria_label: element.getAttribute('aria-label'),
              title: element.getAttribute('title'),
              visible: visible(element),
              in_viewport: inViewport(element),
              bounding_rect: rect(element),
            });
            if (terminal_nodes.length >= 100) break;
          }
          const currentId = (location.pathname.match(/\\/episode\\/(\\d+)/) || [])[1] || null;
          const next_episode_links = [...document.querySelectorAll('a[href]')]
            .map(link => ({
              href: link.href,
              text: (link.innerText || '').trim(),
              class: link.getAttribute('class'),
              aria_label: link.getAttribute('aria-label'),
              title: link.getAttribute('title'),
              visible: visible(link),
              in_viewport: inViewport(link),
            }))
            .filter(link => {
              const match = link.href.match(/\\/episode\\/(\\d+)/);
              return match && match[1] !== currentId;
            });
          return {
            url: location.href,
            page_area_count: areas.length,
            areas,
            terminal_nodes,
            next_episode_links,
          };
        }""",
        list(TERMINAL_TERMS),
    )


async def active_rows(page: Any) -> list[dict[str, Any]]:
    value = await page.evaluate(
        "() => window.__jumpplusProductionCapture ? window.__jumpplusProductionCapture.getActiveRows() : []"
    )
    return value if isinstance(value, list) else []


async def episode_json(page: Any) -> dict[str, Any]:
    raw = await page.evaluate(
        """() => {
          const element = document.querySelector('#episode-json');
          if (!element) return {exists: false, raw: null};
          return {exists: true, raw: element.dataset.value || element.getAttribute('data-value') || null};
        }"""
    )
    raw_value = raw.get("raw") if isinstance(raw, dict) else None
    parsed: Any = None
    parse_error = None
    if isinstance(raw_value, str):
        try:
            parsed = json.loads(raw_value)
        except json.JSONDecodeError as exc:
            parse_error = str(exc)
    pages = ((parsed or {}).get("readableProduct") or {}).get("pageStructure", {}).get("pages")
    if not isinstance(pages, list):
        pages = []
    type_counts = Counter(
        str(item.get("type")) if isinstance(item, dict) else "<non-object>"
        for item in pages
    )
    page_records = [item for item in pages if isinstance(item, dict)]
    return {
        "exists": bool(raw.get("exists")) if isinstance(raw, dict) else False,
        "raw": raw_value,
        "raw_sha256": hashlib.sha256(raw_value.encode()).hexdigest() if isinstance(raw_value, str) else None,
        "parse_error": parse_error,
        "page_structure_pages_total": len(pages),
        "type_counts": dict(type_counts),
        "main_count": sum(item.get("type") == "main" for item in page_records),
        "pages": page_records,
    }


async def controls_snapshot(page: Any) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for name, selector in (
        ("forward", ".page-navigation-forward.js-slide-forward"),
        ("backward", ".page-navigation-backward.js-slide-backward"),
    ):
        locator = page.locator(f"section.viewer.js-viewer {selector}")
        result[name] = [await visible_control(locator.nth(index)) for index in range(await locator.count())]
    return result


def row_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    indices = [int(row.get("pageIndex", -1)) for row in rows if isinstance(row, dict)]
    return {
        "visible_row_count": len(rows),
        "canvas_ids": [row.get("canvasId") for row in rows],
        "page_indices": indices,
        "min_page_index": min(indices) if indices else None,
        "max_page_index": max(indices) if indices else None,
        "source_ids": [
            (row.get("source") or {}).get("sourceId")
            if isinstance(row.get("source"), dict)
            else None
            for row in rows
        ],
        "source_urls": [
            (row.get("source") or {}).get("sourceUrl")
            if isinstance(row.get("source"), dict)
            else None
            for row in rows
        ],
        "canvas_sizes": [
            {"width": row.get("canvasWidth"), "height": row.get("canvasHeight")}
            for row in rows
        ],
    }


async def snapshot(page: Any, adapter: JumpPlusAdapter, *, label: str) -> dict[str, Any]:
    rows = await active_rows(page)
    filtered_rows = await adapter._rows(page)
    try:
        state = await adapter.detect_state(page)
        state_value = page_state_value(state)
    except Exception as exc:  # noqa: BLE001 - preserve the observation
        state_value = f"error:{type(exc).__name__}:{exc}"
    return {
        "timestamp": now_iso(),
        "label": label,
        "url": page.url,
        "episode_id": episode_id_from_url(page.url) if EPISODE_PATH.fullmatch(urlparse(page.url).path) else None,
        "detect_state": state_value,
        "adapter": {
            "content_page_count": adapter._content_page_count,
            "captured_content_page_count": adapter._captured_content_page_count,
            "last_active_max_page_index": adapter._last_active_max_page_index,
            "terminal_reached": adapter._terminal_reached,
            "advance_pending": adapter._advance_pending,
            "first_content_page_index": adapter.first_content_page_index,
        },
        "rows": row_summary(rows),
        "filtered_rows": row_summary(filtered_rows),
        "controls": await controls_snapshot(page),
        "dom": await dom_snapshot(page),
    }


async def wait_samples(
    page: Any,
    adapter: JumpPlusAdapter,
    wait_task: asyncio.Task[Any],
) -> list[dict[str, Any]]:
    del wait_task
    samples = []
    previous = 0
    for point in SAMPLE_POINTS_MS:
        await page.wait_for_timeout(point - previous)
        samples.append(await snapshot(page, adapter, label=f"after_{point}ms"))
        previous = point
    return samples


async def run_case(url: str, output_dir: Path, session: BrowserSession) -> dict[str, Any]:
    case_name = {
        DEFAULT_NORMAL_URL: "normal_long",
        DEFAULT_FREE_URL: "free_timeout",
        DEFAULT_MANUAL_URL: "manual_rental_timeout",
    }.get(url, f"episode_{episode_id_from_url(url)}")
    case_dir = output_dir / case_name
    case_dir.mkdir(parents=True, exist_ok=True)
    expected_episode_id = episode_id_from_url(url)
    page = await session.new_page()
    adapter = JumpPlusAdapter()
    transitions: list[dict[str, Any]] = []
    capture_events: list[dict[str, Any]] = []
    seen_fingerprints: set[str] = set()
    saved_page_count = 0
    error: dict[str, Any] | None = None
    try:
        await adapter.prepare_page(page)
        await adapter.configure_run(page, "direct")
        await page.goto(url, timeout=30_000, wait_until="commit")
        await page.wait_for_timeout(1_000)
        await adapter.initialize(page)
        episode_data = await episode_json(page)
        write_json(case_dir / "episode_json.json", episode_data)
        initial = await snapshot(page, adapter, label="initialized")
        previous_identity = None
        for transition_index in range(MAX_TRANSITIONS):
            state = await adapter.detect_state(page)
            if state in {PageState.END, PageState.NEXT_CONTENT}:
                break
            if state is not PageState.CONTENT:
                error = {"type": "unexpected_state", "message": page_state_value(state)}
                break
            before_capture = await snapshot(page, adapter, label=f"before_capture_{transition_index}")
            identity = await adapter.get_content_identity(page)
            identity_data = {
                "page_id": identity.page_id,
                "page_number": identity.page_number,
                "source_id": identity.source_id,
            }
            captures = await adapter.capture_page(page)
            fingerprints = [fingerprint_bytes(capture.data) for capture in captures or ()]
            new_fingerprints = [fingerprint for fingerprint in fingerprints if fingerprint not in seen_fingerprints]
            saved_page_count += len(new_fingerprints)
            seen_fingerprints.update(new_fingerprints)
            rows_after_capture = await active_rows(page)
            capture_events.append(
                {
                    "transition_index": transition_index,
                    "timestamp": now_iso(),
                    "identity": identity_data,
                    "row_summary": row_summary(rows_after_capture),
                    "capture_result_count": len(captures or ()),
                    "new_fingerprint_count": len(new_fingerprints),
                    "saved_page_count": saved_page_count,
                    "duplicate_fingerprint_count": len(fingerprints) - len(set(fingerprints)),
                    "fingerprints": fingerprints,
                    "adapter_captured_content_page_count": adapter._captured_content_page_count,
                    "capture_debug": await adapter.collect_debug_metadata(page),
                }
            )
            if not new_fingerprints:
                wait_task = asyncio.create_task(adapter.wait_for_change(page, identity))
                samples = await wait_samples(page, adapter, wait_task)
                try:
                    await asyncio.wait_for(wait_task, timeout=12)
                    wait_result = {"status": "changed_or_terminal"}
                except Exception as exc:  # noqa: BLE001
                    wait_result = {"status": "error", "type": type(exc).__name__, "message": str(exc)}
                transitions.append(
                    {"index": transition_index, "kind": "same_capture_wait", "before": before_capture, "samples": samples, "wait_result": wait_result, "after": await snapshot(page, adapter, label=f"after_same_capture_{transition_index}")}
                )
                if wait_result["status"] == "error":
                    error = wait_result
                    break
                continue

            previous_identity = identity
            before_next = await snapshot(page, adapter, label=f"before_go_next_{transition_index}")
            before_url = page.url
            before_terminal = adapter._terminal_reached
            try:
                await adapter.go_next(page)
                go_next_result = {"status": "ok"}
            except Exception as exc:  # noqa: BLE001
                go_next_result = {"status": "error", "type": type(exc).__name__, "message": str(exc)}
            clicked_or_pending = adapter._advance_pending and not before_terminal
            if go_next_result["status"] == "error":
                transitions.append({"index": transition_index, "kind": "go_next_error", "before": before_next, "go_next": go_next_result, "after": await snapshot(page, adapter, label=f"after_go_next_error_{transition_index}")})
                error = go_next_result
                break
            wait_task = asyncio.create_task(adapter.wait_for_change(page, previous_identity))
            samples = await wait_samples(page, adapter, wait_task)
            try:
                await asyncio.wait_for(wait_task, timeout=12)
                wait_result = {"status": "changed_or_terminal"}
            except Exception as exc:  # noqa: BLE001
                wait_result = {"status": "error", "type": type(exc).__name__, "message": str(exc)}
            after = await snapshot(page, adapter, label=f"after_transition_{transition_index}")
            transitions.append(
                {
                    "index": transition_index,
                    "kind": "go_next",
                    "before": before_next,
                    "go_next": {
                        **go_next_result,
                        "clicked_or_pending": clicked_or_pending,
                        "before_url": before_url,
                        "after_url": page.url,
                        "url_changed": page.url != before_url,
                    },
                    "samples": samples,
                    "wait_result": wait_result,
                    "after": after,
                }
            )
            if wait_result["status"] == "error":
                error = wait_result
                break
        final = await snapshot(page, adapter, label="final")
        write_json(case_dir / "transitions.json", transitions)
        write_json(case_dir / "final_state.json", final)
        report = {
            "url": url,
            "expected_episode_id": expected_episode_id,
            "case": case_name,
            "initial": initial,
            "final": final,
            "error": error,
            "transition_count": len(transitions),
            "capture_events": capture_events,
            "saved_page_count": saved_page_count,
            "unique_fingerprint_count": len(seen_fingerprints),
            "total_capture_result_count": sum(
                len(event["fingerprints"]) for event in capture_events
            ),
            "duplicate_capture_count": sum(
                len(event["fingerprints"]) for event in capture_events
            ) - len(seen_fingerprints),
            "expected_main_page_count": episode_data.get("main_count"),
            "content_page_count": adapter._content_page_count,
            "last_active_max_page_index": adapter._last_active_max_page_index,
            "terminal_condition": {
                "captured_count_ge_expected": (
                    adapter._content_page_count is not None
                    and adapter._captured_content_page_count >= adapter._content_page_count
                ),
                "last_index_ge_expected_end": (
                    adapter._content_page_count is not None
                    and adapter._last_active_max_page_index is not None
                    and adapter._last_active_max_page_index
                    >= adapter.first_content_page_index + adapter._content_page_count - 1
                ),
            },
        }
        write_json(case_dir / "report.json", report)
        return report
    except Exception as exc:  # noqa: BLE001 - save a probe-level failure
        failure = {"type": type(exc).__name__, "message": str(exc)}
        write_json(case_dir / "report.json", {"url": url, "case": case_name, "error": failure})
        return {"url": url, "case": case_name, "error": failure}
    finally:
        await session.close_page(page)


def comparison_report(reports: list[dict[str, Any]]) -> dict[str, Any]:
    cases = []
    for report in reports:
        final = report.get("final") or {}
        final_adapter = final.get("adapter") or {}
        final_controls = final.get("controls") or {}
        final_dom = final.get("dom") or {}
        cases.append(
            {
                "case": report.get("case"),
                "url": report.get("url"),
                "episode_id": report.get("expected_episode_id"),
                "main_page_count": report.get("expected_main_page_count"),
                "content_page_count": report.get("content_page_count"),
                "saved_page_count": report.get("saved_page_count"),
                "last_active_page_index": report.get("last_active_max_page_index"),
                "first_content_page_index": final_adapter.get("first_content_page_index"),
                "forward_final": final_controls.get("forward"),
                "next_episode_link_count": len(final_dom.get("next_episode_links", [])),
                "terminal_dom_count": len(final_dom.get("terminal_nodes", [])),
                "final_url": final.get("url"),
                "terminal_condition": report.get("terminal_condition"),
                "error": report.get("error"),
            }
        )
    return {"generated_at": now_iso(), "cases": cases}


async def run_probe(args: argparse.Namespace) -> None:
    args.output_dir.mkdir(parents=True, exist_ok=True)
    session = await BrowserSession.connect(resolve_cdp_endpoint(cli_endpoint=args.cdp_endpoint))
    try:
        reports = []
        for url in (args.normal_url, args.free_url, args.manual_url):
            reports.append(await run_case(url, args.output_dir, session))
        write_json(args.output_dir / "comparison.json", comparison_report(reports))
    finally:
        await session.close()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--normal-url", default=DEFAULT_NORMAL_URL)
    parser.add_argument("--free-url", default=DEFAULT_FREE_URL)
    parser.add_argument("--manual-url", default=DEFAULT_MANUAL_URL)
    parser.add_argument("--cdp-endpoint")
    return parser.parse_args()


if __name__ == "__main__":
    asyncio.run(run_probe(parse_args()))
