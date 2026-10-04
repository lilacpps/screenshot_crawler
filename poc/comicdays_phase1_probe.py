"""Bounded read-only Comic DAYS spread/terminal probe.

This helper uses the shared CDP browser and Playwright only.  It does not
persist page pixels or source bytes; source JPEGs are summarized by header
metadata and a digest.  Only the normal viewer forward control is activated.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import hashlib
import json
import re
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from PIL import Image
from playwright.async_api import Error as PlaywrightError

from screenshot_crawler.core.browser import BrowserSession, resolve_cdp_endpoint
from screenshot_crawler.site_adapters.comicdays.discovery import (
    _series_id_from_page,
    canonical_comicdays_episode_url,
    parse_comicdays_episode_url,
)
from screenshot_crawler.site_adapters.comicdays.live_access import (
    ComicDaysLiveAccessError,
    observe_comicdays_live_access,
)
from screenshot_crawler.site_adapters.comicdays.native_capture import COMICDAYS_CAPTURE_HOOK

DEFAULT_URL = "https://comic-days.com/episode/12207421984241465665"
DEFAULT_OUTPUT = Path("output/comicdays_phase1_probe")
MAX_STEPS = 25
EVAL_TIMEOUT = 8
FORBIDDEN_LABEL_RE = re.compile(
    r"(?:purchase|point|ticket|rental|login|\u8cfc\u5165|\u30dd\u30a4\u30f3\u30c8|"
    r"\u30c1\u30b1\u30c3\u30c8|\u30ec\u30f3\u30bf\u30eb|\u30ed\u30b0\u30a4\u30f3|\u6b21\u306e\u8a71)",
    re.IGNORECASE,
)
FORBIDDEN_LABEL_RE = re.compile(r"(?:purchase|point|ticket|rental|login|購入|ポイント|チケット|レンタル|ログイン|次の話)", re.IGNORECASE)


def redact_url(value: str | None) -> str | None:
    if not value:
        return None
    parsed = urlsplit(value)
    return f"{parsed.scheme}://{parsed.netloc}{parsed.path}" if parsed.scheme else parsed.path


def jpeg_header(data: bytes) -> dict[str, Any]:
    result: dict[str, Any] = {"valid": False, "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}
    try:
        with Image.open(__import__("io").BytesIO(data)) as image:
            result.update({"valid": True, "format": image.format, "size": list(image.size), "mode": image.mode, "progressive": bool(image.info.get("progressive")), "info_keys": sorted(image.info)})
    except Exception as exc:  # noqa: BLE001
        result["error"] = type(exc).__name__
    # Marker scan is deliberately bounded to metadata; no pixels are retained.
    if data[:2] == b"\xff\xd8":
        pos = 2
        markers: list[str] = []
        app_segments: list[dict[str, Any]] = []
        quant_tables: dict[int, list[int]] = {}
        restart_interval = None
        sos_offset = None
        while pos + 4 <= len(data) and len(markers) < 64:
            if data[pos] != 0xFF:
                pos += 1
                continue
            while pos < len(data) and data[pos] == 0xFF:
                pos += 1
            if pos >= len(data):
                break
            marker = data[pos]
            pos += 1
            if marker in {0xD8, 0xD9}:
                markers.append(f"FF{marker:02X}")
                if marker == 0xD9:
                    break
                continue
            if pos + 2 > len(data):
                break
            length = int.from_bytes(data[pos : pos + 2], "big")
            if length < 2 or pos + length > len(data):
                break
            segment = data[pos + 2 : pos + length]
            markers.append(f"FF{marker:02X}")
            if 0xE0 <= marker <= 0xEF:
                app_segments.append({"marker": f"FF{marker:02X}", "length": length, "payload_sha256": hashlib.sha256(segment).hexdigest()})
            if marker == 0xDB:
                qpos = 0
                while qpos < len(segment):
                    info = segment[qpos]
                    qpos += 1
                    precision, table_id = info >> 4, info & 0x0F
                    width = 2 if precision == 1 else 1
                    count = 64 * width
                    if qpos + count > len(segment):
                        break
                    values = [int.from_bytes(segment[qpos + i * width : qpos + (i + 1) * width], "big") for i in range(64)]
                    quant_tables[table_id] = values
                    qpos += count
            if marker == 0xDD and len(segment) >= 2:
                restart_interval = int.from_bytes(segment[:2], "big")
            if marker in {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF} and len(segment) >= 6:
                result["sof"] = {"marker": f"SOF{marker:02X}", "precision": segment[0], "height": int.from_bytes(segment[1:3], "big"), "width": int.from_bytes(segment[3:5], "big"), "components": segment[5]}
                result["sampling"] = [{"id": segment[6 + i * 3], "horizontal": segment[7 + i * 3] >> 4, "vertical": segment[7 + i * 3] & 0x0F, "quant_table": segment[8 + i * 3]} for i in range(segment[5]) if 9 + i * 3 <= len(segment)]
            pos += length
            if marker == 0xDA:
                sos_offset = pos
                break
        result["markers"] = markers
        result["app_segments"] = app_segments
        result["quant_tables"] = quant_tables
        result["restart_interval"] = restart_interval
        if sos_offset is not None:
            result["restart_markers"] = {f"FF{m:02X}": data[sos_offset:].count(bytes((0xFF, m))) for m in range(0xD0, 0xD8)}
        sof = result.get("sof")
        sampling = result.get("sampling") or []
        if isinstance(sof, dict) and sampling:
            result["mcu"] = {"width": 8 * max(int(s.get("horizontal", 1)) for s in sampling), "height": 8 * max(int(s.get("vertical", 1)) for s in sampling), "block_grid": [((int(sof["width"]) + 7) // 8), ((int(sof["height"]) + 7) // 8)]}
    return result


SUMMARY_JS = r"""() => {
  const visible = e => { if (!e) return false; const r=e.getBoundingClientRect(),s=getComputedStyle(e); return r.width>0&&r.height>0&&s.display!=='none'&&s.visibility!=='hidden'&&s.opacity!=='0'; };
  const viewport = e => { if (!visible(e)) return false; const r=e.getBoundingClientRect(); return r.right>0&&r.bottom>0&&r.left<innerWidth&&r.top<innerHeight; };
  const rect = e => { const r=e.getBoundingClientRect(); return {x:r.x,y:r.y,width:r.width,height:r.height}; };
  const child = e => ({tag:e.tagName.toLowerCase(),id:e.id||null,class:e.className||'',onScreen:viewport(e),canvasCount:e.querySelectorAll('canvas').length,imageCount:e.querySelectorAll('img').length,iframeCount:e.querySelectorAll('iframe').length,text:(e.innerText||'').trim().slice(0,200),href:e.getAttribute('href')||null});
  const areas=[...document.querySelectorAll('section.viewer.js-viewer .image-container.js-viewer-content .page-area.js-page-area')];
  const allCanvases=[...document.querySelectorAll('section.viewer.js-viewer canvas.page-image.js-page-image')];
  const row = r => ({areaIndex:r.areaIndex,canvasIndex:r.canvasIndex,canvasId:r.canvasId,rect:r.rect,renderReady:r.renderReady,clipUnsafe:r.clipUnsafe,unsafeSequence:r.unsafeSequence,base:r.base?{sequence:r.base.sequence,sourceId:r.base.sourceId,sourceUrl:r.base.sourceUrl,source:r.base.source}:null,mapping:(r.mapping||[]).map(x=>({sequence:x.sequence,sourceId:x.sourceId,sourceUrl:x.sourceUrl,args:x.args})),mutations:(r.mutations||[]).map(x=>({sequence:x.sequence,operation:x.operation}))});
  const capture=window.__comicDaysProductionCapture?.active?.()||null;
  const control=selector => { const es=[...document.querySelectorAll(selector)]; return {count:es.length,items:es.slice(0,3).map(e=>{const text=(e.innerText||'').trim().slice(0,160),label=[text,e.getAttribute('aria-label')||'',e.getAttribute('title')||'',e.getAttribute('class')||'',e.getAttribute('href')||''].join(' ');return {visible:visible(e),viewport:viewport(e),enabled:!e.disabled&&e.getAttribute('aria-disabled')!=='true',disabled:Boolean(e.disabled)||e.getAttribute('aria-disabled')==='true',href:e.getAttribute('href'),class:e.className||'',text,forbiddenLabel:/(?:purchase|point|ticket|rental|login|購入|ポイント|チケット|レンタル|ログイン|次の話)/i.test(label)}})};
  }
  const viewer=document.querySelector('section.viewer.js-viewer');
  const scope=viewer?.getAttribute('data-json-url')||null;
  const expectedScope=location.href.split('#')[0]+'.json';
  const nextEpisodeLinks=[...document.querySelectorAll('a[href*="/episode/"]')].filter(visible).map(a=>({href:redact(a.href),text:(a.innerText||'').trim().slice(0,160),class:a.className||'',areaIndex:areas.indexOf(a.closest('.page-area.js-page-area'))}));
  return {url:location.href,path:location.pathname,sliderNow:document.querySelector('.js-viewer-slider-pagenum-now')?.textContent?.trim()||null,sliderLast:document.querySelector('.js-viewer-slider-pagenum-last')?.textContent?.trim()||null,viewer:{count:document.querySelectorAll('section.viewer.js-viewer').length,visible:visible(viewer),scope,scopeValid:scope===expectedScope},areas:areas.map((a,i)=>({index:i,id:a.id||null,class:a.className||'',rect:rect(a),visible:visible(a),viewport:viewport(a),canvasCount:a.querySelectorAll('canvas.page-image.js-page-image').length,imageCount:a.querySelectorAll('img').length,iframeCount:a.querySelectorAll('iframe').length,children:[...a.children].map(child)})),canvases:allCanvases.map((c,i)=>({index:i,areaIndex:areas.indexOf(c.closest('.page-area.js-page-area')),width:c.width,height:c.height,rect:rect(c),visible:visible(c),viewport:viewport(c)})),active:capture?{sliderNow:capture.sliderNow,sliderLast:capture.sliderLast,colophon:capture.colophon,complete:capture.complete===true,reason:capture.reason||null,expectedAreaIndices:Array.isArray(capture.expectedAreaIndices)?capture.expectedAreaIndices:[],visibleBodyAreaIndices:Array.isArray(capture.visibleBodyAreaIndices)?capture.visibleBodyAreaIndices:[],rows:(capture.rows||[]).map(row),debug:window.__comicDaysProductionCapture.debug?.()||null}:null,forward:control('.page-navigation-forward.js-slide-forward'),backward:control('.page-navigation-backward.js-slide-backward'),colophon:(()=>{const e=document.querySelector('#viewer-colophon');return e?{visible:visible(e),viewport:viewport(e),areaIndex:areas.indexOf(e),class:e.className||'',text:(e.innerText||'').trim().slice(0,300),children:[...e.children].map(child),links:[...e.querySelectorAll('a[href]')].map(a=>({href:redact(a.href),text:(a.innerText||'').trim().slice(0,160)}))}:null})(),nextEpisodeLinks,nonBody:[...areas].filter((a,i)=>viewport(a)&&!a.querySelector('canvas.page-image.js-page-image')).map((a,i)=>({index:areas.indexOf(a),id:a.id||null,class:a.className||'',text:(a.innerText||'').trim().slice(0,120),canvasCount:a.querySelectorAll('canvas').length,imageCount:a.querySelectorAll('img').length,iframeCount:a.querySelectorAll('iframe').length,children:[...a.children].map(child)}))};
  function redact(v){try{const u=new URL(v,location.href);return u.origin+u.pathname}catch(_){return v}}
}"""


async def evaluate(page: Any) -> dict[str, Any]:
    value = await asyncio.wait_for(page.evaluate(SUMMARY_JS), timeout=EVAL_TIMEOUT)
    value["phase_draws"] = await asyncio.wait_for(page.evaluate("""() => {
      const areas=[...document.querySelectorAll('section.viewer.js-viewer .image-container.js-viewer-content .page-area.js-page-area')];
      const grouped=new Map();
      const currentCanvasId = c => { const refs=window.__comicDaysPhase1CanvasRefs||[]; return refs.indexOf(c)>=0 ? refs.indexOf(c)+1 : null; };
      for (const d of (window.__comicDaysPhase1Draws||[])) {
        const key=d.canvasId;
        if (!grouped.has(key)) grouped.set(key, {canvasId:key,areaIndex:d.areaIndex,canvasWidth:d.canvasWidth,canvasHeight:d.canvasHeight,draws:[]});
        const g=grouped.get(key); g.draws.push(d);
      }
      const current=[...document.querySelectorAll('section.viewer.js-viewer canvas.page-image.js-page-image')];
      return [...grouped.values()].map(g => {
        const base=[...g.draws].reverse().find(d=>d.args?.length===8&&d.args[0]===0&&d.args[1]===0&&d.args[2]===d.sourceWidth&&d.args[3]===d.sourceHeight&&d.args[4]===0&&d.args[5]===0&&d.args[6]===g.canvasWidth&&d.args[7]===g.canvasHeight);
        const source=base?{url:base.sourceUrl,width:base.sourceWidth,height:base.sourceHeight,sourceId:base.sourceId}:null;
        const tiles=base?g.draws.filter(d=>d.sequence>=base.sequence&&d!==base&&d.sourceId===base.sourceId&&d.sourceUrl===base.sourceUrl&&d.args?.length===8&&d.args[2]===d.args[6]&&d.args[3]===d.args[7]):[];
        const canvas=current.find(c=>currentCanvasId(c)===g.canvasId);
        return {canvasId:g.canvasId,areaIndex:canvas?areas.indexOf(canvas.closest('.page-area.js-page-area')):g.areaIndex,canvasWidth:g.canvasWidth,canvasHeight:g.canvasHeight,baseSequence:base?.sequence??null,source,drawCount:g.draws.length,tileCount:tiles.length,lastSequence:g.draws.at(-1)?.sequence??null};
      });
    }"""), timeout=EVAL_TIMEOUT)
    return value


def state_signature(state: dict[str, Any]) -> str:
    """Hash only DOM/provenance state needed to prove repeated stability."""

    active = state.get("active") or {}
    rows = active.get("rows") or []
    compact = {
        "path": state.get("path"),
        "url": state.get("url"),
        "slider": (state.get("sliderNow"), state.get("sliderLast")),
        "viewer": state.get("viewer"),
        "areas": [
            (item.get("index"), item.get("id"), item.get("class"), item.get("viewport"),
             item.get("canvasCount"), item.get("imageCount"), item.get("iframeCount"),
             [(child.get("tag"), child.get("id"), child.get("class"), child.get("onScreen"),
               child.get("canvasCount"), child.get("imageCount"), child.get("iframeCount"))
              for child in item.get("children", [])])
            for item in state.get("areas", [])
        ],
        "rows": [
            (row.get("areaIndex"), row.get("canvasId"), row.get("renderReady"),
             (row.get("base") or {}).get("sequence"), (row.get("base") or {}).get("sourceId"),
             tuple(item.get("sequence") for item in row.get("mapping", [])))
            for row in rows
        ],
        "forward": state.get("forward"),
        "backward": state.get("backward"),
        "colophon": state.get("colophon"),
        "nonBody": state.get("nonBody"),
        "nextEpisodeLinks": state.get("nextEpisodeLinks"),
    }
    return hashlib.sha256(json.dumps(compact, ensure_ascii=True, sort_keys=True, default=str).encode()).hexdigest()


async def wait_stable(page: Any, before: dict[str, Any], limit_ms: int = 10_000) -> dict[str, Any]:
    deadline = asyncio.get_running_loop().time() + limit_ms / 1000
    last: dict[str, Any] = before
    started = asyncio.get_running_loop().time()
    previous_signature: str | None = None
    stable_count = 0
    samples: list[dict[str, Any]] = []
    while asyncio.get_running_loop().time() < deadline:
        try:
            last = await evaluate(page)
        except (TimeoutError, PlaywrightError):
            await page.wait_for_timeout(250)
            continue
        signature = state_signature(last)
        stable_count = stable_count + 1 if signature == previous_signature else 1
        previous_signature = signature
        rows = ((last.get("active") or {}).get("rows") or [])
        colophon = last.get("colophon") or {}
        samples.append({
            "elapsed_ms": round((asyncio.get_running_loop().time() - started) * 1000, 1),
            "path": last.get("path"),
            "slider_now": last.get("sliderNow"),
            "slider_last": last.get("sliderLast"),
            "signature": signature,
            "rows_ready": bool(rows) and all(r.get("renderReady") is True for r in rows),
            "colophon_viewport": colophon.get("viewport") is True,
            "stable_count": stable_count,
        })
        if last.get("url") != before.get("url"):
            last["stability"] = {"samples": samples, "elapsed_ms": samples[-1]["elapsed_ms"], "stable_count": stable_count, "stop": "url_change"}
            return last
        rows_ready = bool(rows) and all(r.get("renderReady") is True for r in rows)
        colophon_ready = colophon.get("viewport") is True
        if stable_count >= 3 and (rows_ready or colophon_ready):
            last["stability"] = {"samples": samples, "elapsed_ms": samples[-1]["elapsed_ms"], "stable_count": stable_count, "stop": "positive_body_or_colophon"}
            return last
        await page.wait_for_timeout(250)
    last["stability"] = {"samples": samples, "elapsed_ms": samples[-1]["elapsed_ms"] if samples else 0, "stable_count": stable_count, "stop": "deadline"}
    return last


def forward_control_allowed(state: dict[str, Any], expected_path: str) -> tuple[bool, str]:
    controls = state.get("forward") or {}
    if controls.get("count") != 1:
        return False, "forward_count"
    items = controls.get("items") or []
    if len(items) != 1:
        return False, "forward_item_count"
    control = items[0]
    if control.get("visible") is not True or control.get("enabled") is not True:
        return False, "forward_not_visible_enabled"
    label = " ".join(
        str(control.get(key) or "") for key in ("text", "href", "class")
    )
    if control.get("forbiddenLabel") is True or FORBIDDEN_LABEL_RE.search(label) or "/episode/" in str(control.get("href") or ""):
        return False, "forward_forbidden_or_episode_href"
    if state.get("path") != expected_path:
        return False, "target_path_changed"
    return True, "ok"


async def source_metadata(page: Any, state: dict[str, Any]) -> list[dict[str, Any]]:
    ids = []
    for row in ((state.get("active") or {}).get("rows") or []):
        base = row.get("base") or {}
        if base.get("sourceId") not in ids:
            ids.append(base.get("sourceId"))
    if not ids:
        return []
    payload = await asyncio.wait_for(page.evaluate("ids => window.__comicDaysProductionCapture?.snapshot(ids) || []", ids), timeout=EVAL_TIMEOUT)
    result = []
    for item in payload if isinstance(payload, list) else []:
        if not isinstance(item, dict) or not isinstance(item.get("bytes"), str):
            result.append({"id": item.get("id") if isinstance(item, dict) else None, "error": item.get("error") if isinstance(item, dict) else "invalid"})
            continue
        raw = base64.b64decode(item["bytes"], validate=True)
        summary = jpeg_header(raw)
        summary.update({"id": item.get("id"), "url": redact_url(item.get("url"))})
        result.append(summary)
    return result


async def run(url: str, output: Path, endpoint: str | None, max_steps: int = MAX_STEPS) -> None:
    output.mkdir(parents=True, exist_ok=True)
    session = await BrowserSession.connect(resolve_cdp_endpoint(cli_endpoint=endpoint))
    page = await session.new_page()
    observations: list[dict[str, Any]] = []
    target_path = urlsplit(url).path
    identity: dict[str, Any] = {"target_url": redact_url(url), "target_path": target_path}
    access: dict[str, Any] = {}
    try:
        await page.add_init_script(script=COMICDAYS_CAPTURE_HOOK)
        await page.add_init_script(script=r"""
(() => {
  const old = CanvasRenderingContext2D.prototype.drawImage;
  let next = 1;
  const ids = new WeakMap();
  const identify = c => { if (!ids.has(c)) ids.set(c, next++); return ids.get(c); };
  const args = (a, s) => { const w=s?.width||0,h=s?.height||0; if(a.length===3)return [0,0,w,h,Number(a[1]),Number(a[2]),w,h]; if(a.length===5)return [0,0,w,h,Number(a[1]),Number(a[2]),Number(a[3]),Number(a[4])]; if(a.length===9)return [...a.slice(1,9)].map(Number); return null; };
  window.__comicDaysPhase1Draws = [];
  window.__comicDaysPhase1CanvasRefs = [];
  CanvasRenderingContext2D.prototype.drawImage = function(source, ...a) {
    try { const c=this.canvas, area=c?.closest?.('.page-area.js-page-area'), id=identify(c); if (!window.__comicDaysPhase1CanvasRefs.includes(c)) window.__comicDaysPhase1CanvasRefs.push(c); const sourceId=source?.__comicDaysPhase1Id || (source.__comicDaysPhase1Id=window.__comicDaysPhase1Draws.length+1); window.__comicDaysPhase1Draws.push({sequence:window.__comicDaysPhase1Draws.length,canvasId:id,areaIndex:[...document.querySelectorAll('.page-area.js-page-area')].indexOf(area),canvasWidth:c.width,canvasHeight:c.height,args:args([source,...a],source),sourceId,sourceUrl:source?.currentSrc||source?.src||'',sourceWidth:Number(source?.naturalWidth||source?.width)||0,sourceHeight:Number(source?.naturalHeight||source?.height)||0}); } catch (_) {} return old.apply(this,[source,...a]);
  };
})();
""")
        await page.goto(url, wait_until="domcontentloaded", timeout=30_000)
        await page.wait_for_timeout(3_000)
        episode_id = parse_comicdays_episode_url(page.url)
        identity["episode_id"] = episode_id
        identity["canonical_url_match"] = (
            episode_id is not None
            and page.url == canonical_comicdays_episode_url(page.url)
            and target_path == urlsplit(page.url).path
        )
        try:
            work_id = await _series_id_from_page(page)
            identity["work_id"] = work_id
            live = await observe_comicdays_live_access(
                page,
                series_id=work_id,
                episode_id=episode_id or "",
                timeout_ms=15_000,
            )
            access = {
                "access_mode": live.access_mode,
                "grant_until": live.grant_until.isoformat() if live.grant_until else None,
                "grant_observed": live.grant_observed,
                "ticket_is_charged": live.ticket.is_charged,
                "ticket_charged_at": live.ticket.charged_at.isoformat() if live.ticket.charged_at else None,
            }
        except (ComicDaysLiveAccessError, PlaywrightError, TimeoutError) as exc:
            access = {"error": type(exc).__name__, "message": str(exc)}
        current = await wait_stable(page, await evaluate(page), 12_000)
        current["label"] = "first"
        current["source_metadata"] = await source_metadata(page, current)
        observations.append(current)
        can_operate = (
            identity.get("canonical_url_match") is True
            and access.get("access_mode") == "free"
        ) or (
            identity.get("canonical_url_match") is True
            and access.get("access_mode") == "quota"
            and access.get("grant_until") is not None
            and access.get("grant_observed") is True
        )
        for step in range(1, max_steps + 1):
            before = observations[-1]
            if before.get("path") != target_path:
                break
            if before.get("colophon", {}).get("viewport") is True:
                before["transition_stop"] = "positive_colophon"
                break
            allowed, reason = forward_control_allowed(before, target_path)
            before["forward_guard"] = {"allowed": allowed and can_operate, "reason": reason if can_operate else "access_not_free_or_active_grant"}
            if not can_operate or not allowed:
                break
            before_slider = before.get("sliderNow")
            locator = page.locator("section.viewer.js-viewer .page-navigation-forward.js-slide-forward")
            try:
                await locator.click(timeout=2_000, no_wait_after=True)
            except (PlaywrightError, TimeoutError) as exc:
                before["transition_error"] = {"type": type(exc).__name__, "message": str(exc)}
                break
            await page.wait_for_timeout(150)
            after = await wait_stable(page, before, 8_000)
            after["label"] = f"forward_{step}"
            after["before_slider"] = before_slider
            before_scope = (before.get("viewer") or {}).get("scope")
            after_scope = (after.get("viewer") or {}).get("scope")
            after["source_metadata"] = await source_metadata(page, after) if after.get("path") == target_path else []
            observations.append(after)
            if after.get("path") != target_path:
                after["transition_stop"] = "url_or_episode_change"
                break
            if after.get("url") != before.get("url") or after_scope != before_scope:
                after["transition_stop"] = "url_or_viewer_scope_change"
                break
            if after.get("colophon", {}).get("viewport"):
                after["transition_stop"] = "positive_colophon"
                break
    finally:
        (output / "report.json").write_text(json.dumps({"target_url": redact_url(url), "identity": identity, "access": access, "observations": observations}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        await session.close_page(page)
        await session.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default=DEFAULT_URL)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--cdp-endpoint")
    parser.add_argument("--max-steps", type=int, default=MAX_STEPS)
    args = parser.parse_args()
    asyncio.run(run(args.url, args.output, args.cdp_endpoint, max(0, args.max_steps)))


if __name__ == "__main__":
    main()
