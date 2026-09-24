"""Phase-A read-only probe for Jump+ illustration transit-guide failures.

The probe discovers current special rows from an isolated Catalog, then runs
the production viewer observation/capture flow against those rows.  It only
uses the viewer forward/back controls through the production adapter; it never
clicks a transit guide, episode link, rental, purchase, point, ticket, or
login control.  The production adapter is intentionally not modified by this
probe.
"""

from __future__ import annotations

import argparse
import asyncio
import inspect
import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from screenshot_crawler.core.browser import BrowserSession, resolve_cdp_endpoint
from screenshot_crawler.core.fingerprint import fingerprint_bytes
from screenshot_crawler.core.state import PageState
from screenshot_crawler.site_adapters.jumpplus.adapter import JumpPlusAdapter

DEFAULT_CATALOG = Path("output/jumpplus_special_guide_phase_a/catalog.sqlite")
DEFAULT_OUTPUT = Path("output/jumpplus_special_guide_phase_a")
SPECIAL_LABELS = ("イラスト", "イラスト2", "イラスト3")
BASE_SAMPLE_POINTS_MS = (0, 100, 300, 500, 1_000, 2_000, 3_000, 5_000)
EXTENDED_SAMPLE_POINTS_MS = (8_000, 10_000, 15_000)


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")


def catalog_special_urls(catalog: Path) -> list[dict[str, str]]:
    with sqlite3.connect(catalog) as connection:
        rows = connection.execute(
            """
            SELECT i.order_label, s.external_id, s.access_mode
            FROM items AS i JOIN sources AS s ON s.item_id = i.id
            WHERE i.order_label IN (?, ?, ?) AND s.site = 'jumpplus'
            ORDER BY CASE i.order_label WHEN ? THEN 1 WHEN ? THEN 2 WHEN ? THEN 3 END
            """,
            (*SPECIAL_LABELS, *SPECIAL_LABELS),
        ).fetchall()
    return [
        {
            "label": str(label),
            "episode_id": str(episode_id),
            "access_mode": str(access_mode),
            "url": f"https://shonenjumpplus.com/episode/{episode_id}",
        }
        for label, episode_id, access_mode in rows
    ]


async def guide_snapshot(page: Any, adapter: JumpPlusAdapter) -> dict[str, Any]:
    dom = await page.evaluate(
        """() => {
          const attrs = element => Object.fromEntries([...element.attributes].map(a => [a.name, a.value]));
          const rect = element => { const r = element.getBoundingClientRect(); return {x:r.x,y:r.y,width:r.width,height:r.height,top:r.top,right:r.right,bottom:r.bottom,left:r.left}; };
          const style = element => { const s = getComputedStyle(element); return {display:s.display,visibility:s.visibility,opacity:s.opacity,pointerEvents:s.pointerEvents,zIndex:s.zIndex,position:s.position,transform:s.transform,transition:s.transition,animation:s.animation}; };
          const state = element => ({tag:element.tagName.toLowerCase(),id:element.id || null,class:element.getAttribute('class'),data:attrs(element),aria:Object.fromEntries([...element.attributes].filter(a => a.name.startsWith('aria-')).map(a => [a.name,a.value])),text:(element.innerText || '').trim(),visible:rect(element).width > 0 && rect(element).height > 0 && style(element).display !== 'none' && style(element).visibility !== 'hidden',in_viewport:rect(element).bottom > 0 && rect(element).right > 0 && rect(element).left < innerWidth && rect(element).top < innerHeight,bounding_rect:rect(element),computed:style(element),parent:element.parentElement ? {tag:element.parentElement.tagName.toLowerCase(),id:element.parentElement.id || null,class:element.parentElement.getAttribute('class')} : null});
          const guides = [...document.querySelectorAll('.js-slide-to-transit-guide')].map(state);
          const viewer = document.querySelector('section.viewer.js-viewer');
          const areas = [...(viewer?.querySelectorAll('.page-area.js-page-area') || [])].map((element, index) => ({
            dom_index:index, tag:element.tagName.toLowerCase(), class:element.getAttribute('class'), data:attrs(element),
            aria:Object.fromEntries([...element.attributes].filter(a => a.name.startsWith('aria-')).map(a => [a.name,a.value])),
            visible:state(element).visible, in_viewport:state(element).in_viewport, bounding_rect:rect(element),
            canvas_count:element.querySelectorAll('canvas').length, link_count:element.querySelectorAll('a[href]').length,
            canvases:[...element.querySelectorAll('canvas')].map(canvas => ({id:canvas.id || null,class:canvas.getAttribute('class'),width:canvas.width,height:canvas.height,visible:state(canvas).visible,in_viewport:state(canvas).in_viewport})),
            links:[...element.querySelectorAll('a[href]')].map(link => ({href:link.href,text:(link.innerText || '').trim(),class:link.getAttribute('class'),visible:state(link).visible}))
          }));
          const forward = document.querySelector('.page-navigation-forward.js-slide-forward');
          const backward = document.querySelector('.page-navigation-backward.js-slide-backward');
          const center = forward ? (() => { const r=forward.getBoundingClientRect(); return {x:r.left+r.width/2,y:r.top+r.height/2}; })() : null;
          return {guides,areas,forward:forward ? state(forward) : null,backward:backward ? state(backward) : null,forward_center:center,elements_from_point:center ? document.elementsFromPoint(center.x,center.y).slice(0,12).map(state) : []};
        }"""
    )
    try:
        rows = await adapter._rows(page)
    except Exception as exc:  # noqa: BLE001 - preserve transient state
        rows = [{"error": f"{type(exc).__name__}: {exc}"}]
    return {
        "timestamp": now_iso(),
        "url": page.url,
        "adapter": {
            "content_page_count": adapter._content_page_count,
            "first_content_page_index": adapter._first_content_page_index,
            "captured_content_page_count": adapter._captured_content_page_count,
            "last_active_max_page_index": adapter._last_active_max_page_index,
            "terminal_reached": adapter._terminal_reached,
            "advance_pending": adapter._advance_pending,
        },
        "rows": rows,
        "guide_dom": dom,
    }


async def page_structure(page: Any) -> dict[str, Any]:
    return await page.evaluate(
        """() => {
          const node = document.querySelector('#episode-json');
          const raw = node?.dataset.value || node?.getAttribute('data-value') || null;
          let parsed = null, parseError = null;
          try { if (raw) parsed = JSON.parse(raw); } catch (e) { parseError = String(e); }
          const pages = parsed?.readableProduct?.pageStructure?.pages;
          return {exists:!!node,raw,parse_error:parseError,pages:Array.isArray(pages) ? pages : [],main_count:Array.isArray(pages) ? pages.filter(p => p && p.type === 'main').length : 0};
        }"""
    )


async def persistence_observation(page: Any) -> dict[str, Any]:
    # Record names/metadata only; values are intentionally not persisted.
    return await page.evaluate(
        """() => ({
          local_storage_keys: Object.keys(localStorage),
          session_storage_keys: Object.keys(sessionStorage),
          cookie_names: document.cookie.split(';').map(x => x.trim().split('=')[0]).filter(Boolean),
          jumpplus_globals: Object.keys(window).filter(k => /jump|episode|readable|transit|viewer/i.test(k)).slice(0,200)
        })"""
    )


class TracingAdapter(JumpPlusAdapter):
    def __init__(self) -> None:
        super().__init__()
        self.forward_calls: list[dict[str, Any]] = []

    async def _click_forward(self, page: Any) -> None:
        caller = inspect.currentframe().f_back.f_code.co_name if inspect.currentframe() and inspect.currentframe().f_back else "unknown"
        event: dict[str, Any] = {"callsite": caller, "started_at": now_iso(), "samples": []}

        async def sample() -> None:
            previous = 0
            guide_seen = False
            for point in BASE_SAMPLE_POINTS_MS:
                await page.wait_for_timeout(point - previous)
                state = await guide_snapshot(page, self)
                event["samples"].append({"offset_ms": point, "state": state})
                guide_seen = guide_seen or any(item.get("visible") for item in state["guide_dom"].get("guides", []))
                previous = point
            if guide_seen:
                for point in EXTENDED_SAMPLE_POINTS_MS:
                    await page.wait_for_timeout(point - previous)
                    state = await guide_snapshot(page, self)
                    event["samples"].append({"offset_ms": point, "state": state})
                    previous = point

        sampler = asyncio.create_task(sample())
        try:
            await super()._click_forward(page)
            event["result"] = "ok"
        except Exception as exc:
            event["result"] = "error"
            event["error"] = {"type": type(exc).__name__, "message": str(exc)}
            raise
        finally:
            try:
                await sampler
            except Exception as exc:  # noqa: BLE001 - probe should retain partial samples
                event["sampler_error"] = {"type": type(exc).__name__, "message": str(exc)}
            event["finished_at"] = now_iso()
            event["after"] = await guide_snapshot(page, self)
            self.forward_calls.append(event)


async def run_episode(url: str, label: str, output_dir: Path, session: BrowserSession) -> dict[str, Any]:
    case_dir = output_dir / label
    case_dir.mkdir(parents=True, exist_ok=True)
    page = await session.new_page()
    adapter = TracingAdapter()
    report: dict[str, Any] = {"label": label, "url": url, "started_at": now_iso(), "transitions": [], "capture_events": []}
    fingerprints: set[str] = set()
    try:
        await adapter.prepare_page(page)
        await adapter.configure_run(page, "direct")
        await page.goto(url, timeout=30_000, wait_until="commit")
        await page.wait_for_timeout(1_000)
        write_json(case_dir / "episode_json.json", await page_structure(page))
        write_json(case_dir / "persistence.json", await persistence_observation(page))
        report["before_initialize"] = await guide_snapshot(page, adapter)
        await adapter.initialize(page)
        report["after_initialize"] = await guide_snapshot(page, adapter)
        report["forward_calls_after_initialize"] = len(adapter.forward_calls)

        for index in range(32):
            state = await adapter.detect_state(page)
            if state in {PageState.END, PageState.NEXT_CONTENT}:
                report["terminal_before_capture"] = {"index": index, "state": state.value}
                break
            if state is not PageState.CONTENT:
                report["error"] = {"type": "UnexpectedState", "message": state.value}
                break
            identity = await adapter.get_content_identity(page)
            before = await guide_snapshot(page, adapter)
            captures = await adapter.capture_page(page)
            capture_hashes = [fingerprint_bytes(c.data) for c in captures or ()]
            fingerprints.update(capture_hashes)
            report["capture_events"].append({
                "index": index,
                "timestamp": now_iso(),
                "identity": {"page_id": identity.page_id, "source_id": identity.source_id},
                "capture_result_count": len(captures or ()),
                "capture_hashes": capture_hashes,
                "new_capture_count": len(set(capture_hashes)),
                "before_go_next": before,
                "adapter": {"content_page_count": adapter._content_page_count,"first_content_page_index": adapter._first_content_page_index,"captured_content_page_count": adapter._captured_content_page_count,"last_active_max_page_index": adapter._last_active_max_page_index},
            })
            transition: dict[str, Any] = {"index": index, "before": before, "url_before": page.url}
            try:
                await adapter.go_next(page)
                transition["go_next"] = "ok"
            except Exception as exc:  # noqa: BLE001 - exact production failure
                transition["go_next"] = {"type": type(exc).__name__, "message": str(exc)}
                transition["after_go_next_error"] = await guide_snapshot(page, adapter)
                report["transitions"].append(transition)
                report["error"] = transition["go_next"]
                break
            transition["url_after_go_next"] = page.url
            transition["forward_call_count"] = len(adapter.forward_calls)
            try:
                await adapter.wait_for_change(page, identity)
                transition["wait_for_change"] = "ok"
            except Exception as exc:  # noqa: BLE001 - save timeout snapshot
                transition["wait_for_change"] = {"type": type(exc).__name__, "message": str(exc)}
                report["error"] = transition["wait_for_change"]
            transition["after"] = await guide_snapshot(page, adapter)
            report["transitions"].append(transition)
            if isinstance(transition["wait_for_change"], dict):
                break

        report["after_run"] = await guide_snapshot(page, adapter)
        report["forward_calls"] = adapter.forward_calls
        report["saved_unique_page_count"] = len(fingerprints)
        report["saved_capture_result_count"] = sum(int(e["capture_result_count"]) for e in report["capture_events"])
        report["expected_main_page_count"] = (json.loads((case_dir / "episode_json.json").read_text(encoding="utf-8"))).get("main_count")
        report["adapter_final"] = {"content_page_count": adapter._content_page_count,"first_content_page_index": adapter._first_content_page_index,"captured_content_page_count": adapter._captured_content_page_count,"last_active_max_page_index": adapter._last_active_max_page_index,"terminal_reached": adapter._terminal_reached,"advance_pending": adapter._advance_pending}
        report["finished_at"] = now_iso()
        write_json(case_dir / "transitions.json", report["transitions"])
        write_json(case_dir / "forward_calls.json", adapter.forward_calls)
        write_json(case_dir / "report.json", report)
        return report
    except Exception as exc:  # noqa: BLE001 - preserve probe failure
        report["error"] = {"type": type(exc).__name__, "message": str(exc)}
        report["forward_calls"] = adapter.forward_calls
        write_json(case_dir / "forward_calls.json", adapter.forward_calls)
        write_json(case_dir / "report.json", report)
        return report
    finally:
        await session.close_page(page)


async def main(args: argparse.Namespace) -> None:
    special = catalog_special_urls(args.catalog) if not args.only_url else []
    if not special and not args.only_url:
        raise RuntimeError(f"no current special rows found in {args.catalog}")
    output = args.output_dir
    output.mkdir(parents=True, exist_ok=True)
    write_json(output / "targets.json", special)
    session = await BrowserSession.connect(resolve_cdp_endpoint(cli_endpoint=args.cdp_endpoint))
    try:
        reports = []
        for target in special:
            if target["access_mode"] != "free":
                continue
            reports.append(await run_episode(target["url"], target["label"], output, session))
        if args.only_url:
            reports.append(await run_episode(args.only_url, "normal_free_comparison", output, session))
        elif args.normal_url and not args.skip_normal:
            reports.append(await run_episode(args.normal_url, "normal_free_comparison", output, session))
        write_json(output / "comparison.json", reports)
    finally:
        await session.close()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--normal-url", default="https://shonenjumpplus.com/episode/9253191256637716604")
    parser.add_argument("--only-url", help="probe only this URL, without catalog special rows")
    parser.add_argument("--skip-normal", action="store_true", help="probe catalog special rows only")
    parser.add_argument("--cdp-endpoint")
    return parser.parse_args()


if __name__ == "__main__":
    asyncio.run(main(parse_args()))
