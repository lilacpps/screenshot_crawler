"""Site-local Comic DAYS canvas provenance and native PNG reconstruction."""

from __future__ import annotations

import io
import tempfile
from itertools import pairwise
from pathlib import Path
from typing import Any

from PIL import Image

from screenshot_crawler.core.capture import CaptureResult, capture_png_bytes

MAX_SOURCE_BYTES = 2_000_000
MAX_ROWS = 4
_JPEG_SOF_BASELINE = 0xC0
_JPEG_SOF_PROGRESSIVE = {0xC2, 0xC6, 0xCA, 0xCE}

COMICDAYS_CAPTURE_HOOK = r"""
(() => {
  if (window.__comicDaysProductionCapture) return;
  const s = { canvases:new WeakMap(), images:new WeakMap(), canvasNext:1, imageNext:1,
    imageRefs:new Map(), draws:[], mutations:[], unsafeSequence:new WeakMap(), clipUnsafe:new Set(), clipSequence:new Map(), seq:0 };
  const cap = 6000, maxImages = 256;
  const trim = a => { if (a.length > cap) a.splice(0, a.length-cap); };
  const mutation = (c, operation, args, extra={}) => { const id=canvas(c), sequence=s.seq++; const value={sequence,canvasId:id,operation,args,...extra}; s.mutations.push(value); trim(s.mutations); s.unsafeSequence.set(c,sequence); return sequence; };
  const canvas = c => { let id=s.canvases.get(c); if(!id){id=s.canvasNext++;s.canvases.set(c,id)} return id; };
  const image = x => { if(!(x instanceof HTMLImageElement)) return null; let id=s.images.get(x);
    if(!id){if(s.imageRefs.size >= maxImages)return null;id=s.imageNext++;s.images.set(x,id);s.imageRefs.set(id,x)}
    return {id,url:x.currentSrc||x.src||'',width:Number(x.naturalWidth||x.width)||0,height:Number(x.naturalHeight||x.height)||0}; };
  const args = (a,x) => { const w=x?.width||0,h=x?.height||0;
    if(a.length===3)return [0,0,w,h,Number(a[1]),Number(a[2]),w,h];
    if(a.length===5)return [0,0,w,h,Number(a[1]),Number(a[2]),Number(a[3]),Number(a[4])];
    if(a.length===9)return [...a.slice(1,9)].map(Number); return null; };
  const state = ctx => { let m=null; try{m=ctx.getTransform()}catch(_){ }
    return {a:m?.a,b:m?.b,c:m?.c,d:m?.d,e:m?.e,f:m?.f,alpha:Number(ctx.globalAlpha),composite:ctx.globalCompositeOperation,filter:ctx.filter}; };
  const proto=CanvasRenderingContext2D.prototype;
  if(!proto.drawImage.__comicDaysProduction){ const old=proto.drawImage; function wrapped(...a){try{
    const x=image(a[0]), r=args(a,x), c=this.canvas; if(x&&r){s.draws.push({sequence:s.seq++,canvasId:canvas(c),canvasWidth:c.width,canvasHeight:c.height,source:x,sourceId:x.id,sourceUrl:x.url,args:r,state:state(this) });trim(s.draws)} else {mutation(c,'drawImage',undefined,{unsupported:true})}
  }catch(_){ } return old.apply(this,a) } wrapped.__comicDaysProduction=true; proto.drawImage=wrapped; }
  for(const name of ['clearRect','fillRect','putImageData','clip','fill','stroke','fillText','strokeText']){
    const old=proto[name]; if(typeof old!=='function'||old.__comicDaysProduction)continue;
    function wrapped(...a){try{const c=this.canvas,id=canvas(c);if(name==='clip'){s.clipUnsafe.add(id);if(!s.clipSequence.has(id))s.clipSequence.set(id,s.seq)}if(name==='clearRect')s.draws.splice(0,s.draws.length,...s.draws.filter(item=>item.canvasId!==id));mutation(c,name,a.slice(0,4))}catch(_){ }return old.apply(this,a)}
    wrapped.__comicDaysProduction=true;proto[name]=wrapped;
  }
  if (typeof proto.reset === 'function' && !proto.reset.__comicDaysProduction) {
    const oldReset = proto.reset;
    function reset(...a){try{const c=this.canvas,id=canvas(c);s.draws.splice(0,s.draws.length,...s.draws.filter(item=>item.canvasId!==id));s.clipUnsafe.delete(id);s.clipSequence.delete(id);mutation(c,'reset');s.unsafeSequence.delete(c)}catch(_){ }return oldReset.apply(this,a)}
    reset.__comicDaysProduction=true;proto.reset=reset;
  }
  for (const name of ['width','height']) {
    const descriptor = Object.getOwnPropertyDescriptor(HTMLCanvasElement.prototype, name);
    if (!descriptor?.set || descriptor.set.__comicDaysProduction) continue;
    const original = descriptor.set;
    function resize(value) {
      const id = s.canvases.get(this);
      if (id) {
        const hadDraws = s.draws.some(item => item.canvasId === id);
        if (hadDraws) s.draws.splice(0, s.draws.length, ...s.draws.filter(item => item.canvasId !== id));
        s.clipUnsafe.delete(id); s.clipSequence.delete(id);
        if (hadDraws) mutation(this,'resize',undefined,{value:Number(value)});
        s.unsafeSequence.delete(this);
      }
      return original.call(this,value);
    }
    resize.__comicDaysProduction=true;
    Object.defineProperty(HTMLCanvasElement.prototype,name,{...descriptor,set:resize});
  }
  const visible=e=>{if(!e)return false;const own=getComputedStyle(e);if(own.display==='none'||own.visibility==='hidden'||own.opacity==='0')return false;const r=e.getBoundingClientRect();if(!(r.width>0&&r.height>0))return false;let left=Math.max(r.left,0),right=Math.min(r.right,innerWidth),top=Math.max(r.top,0),bottom=Math.min(r.bottom,innerHeight);for(let p=e.parentElement;p;p=p.parentElement){const q=getComputedStyle(p);if(q.display==='none'||q.visibility==='hidden'||q.opacity==='0')return false;if(['hidden','clip','scroll','auto'].includes(q.overflowX)){const x=p.getBoundingClientRect();left=Math.max(left,x.left);right=Math.min(right,x.right)}if(['hidden','clip','scroll','auto'].includes(q.overflowY)){const x=p.getBoundingClientRect();top=Math.max(top,x.top);bottom=Math.min(bottom,x.bottom)}}const area=Math.max(0,right-left)*Math.max(0,bottom-top);return area/(r.width*r.height)>=.5};
  const row=(c,areas)=>{const area=c.closest('.page-area.js-page-area');const ai=areas.indexOf(area);if(ai<0)return null;const r=c.getBoundingClientRect();if(!visible(c))return null;const id=canvas(c);const all=s.draws.filter(x=>x.canvasId===id);const safe=x=>{const q=x.state||{};return q.a===1&&q.b===0&&q.c===0&&q.d===1&&q.e===0&&q.f===0&&q.alpha===1&&q.composite==='source-over'&&q.filter==='none'};const full=x=>x.args?.length===8&&x.args[0]===0&&x.args[1]===0&&x.args[2]===x.source.width&&x.args[3]===x.source.height&&x.args[4]===0&&x.args[5]===0&&x.args[6]===x.canvasWidth&&x.args[7]===x.canvasHeight;
    const bases=all.filter(full);const base=bases.at(-1);const draws=base?all.filter(x=>x.sequence>=base.sequence):all;const tiles=draws.filter(x=>x!==base);
    const exactUnion=(rects,w,h)=>{if(rects.length!==16||rects.some(x=>x.some(v=>!Number.isInteger(v))))return null;const widths=[...new Set(rects.map(x=>x[2]))],heights=[...new Set(rects.map(x=>x[3]))];if(widths.length!==1||heights.length!==1||widths[0]<=0||heights[0]<=0)return null;const xs=[...new Set(rects.map(x=>x[0]))].sort((a,b)=>a-b),ys=[...new Set(rects.map(x=>x[1]))].sort((a,b)=>a-b);if(xs.length!==4||ys.length!==4||xs[0]!==0||ys[0]!==0)return null;for(let i=1;i<4;i++){if(xs[i]!==xs[i-1]+widths[0]||ys[i]!==ys[i-1]+heights[0])return null}const maxX=xs[3]+widths[0];if(maxX>w||ys[3]+heights[0]!==h)return null;const pairs=new Set(rects.map(x=>`${x[0]}:${x[1]}`));for(const x of xs)for(const y of ys)if(!pairs.has(`${x}:${y}`))return null;return {maxX};};
    const outside=x=>{const a=x.args||[];return a.length===8&&(a[4]+a[6]<=0||a[5]+a[7]<=0||a[4]>=x.canvasWidth||a[5]>=x.canvasHeight)};
    const usable=tiles.filter(x=>!outside(x));
    const valid=!!base&&safe(base)&&usable.length>0&&usable.every(x=>safe(x)&&Array.isArray(x.args)&&x.args.length===8&&x.args.every(Number.isFinite)&&x.args[2]===x.args[6]&&x.args[3]===x.args[7]&&x.args[2]>0&&x.args[3]>0&&x.args[0]>=0&&x.args[1]>=0&&x.args[0]+x.args[2]<=base.source.width&&x.args[1]+x.args[3]<=base.source.height&&x.args[4]>=0&&x.args[5]>=0&&x.args[4]+x.args[6]<=x.canvasWidth&&x.args[5]+x.args[7]<=x.canvasHeight);
    const dest=valid?exactUnion(usable.map(x=>x.args.slice(4,8)),base.canvasWidth,base.canvasHeight):null;const src=valid?exactUnion(usable.map(x=>x.args.slice(0,4)),base.source.width,base.source.height):null;const latest=usable.length?Math.max(...usable.map(x=>x.sequence)):base?.sequence;const clipDuring=!!base&&s.clipUnsafe.has(id)&&Number(s.clipSequence.get(id))<=Number(latest);const renderReady=!!base&&!!dest&&!!src&&!clipDuring&&(base.canvasWidth-dest.maxX===base.source.width-src.maxX);return {areaIndex:ai,canvasId:id,probeId:id,sliderNow:Number(document.querySelector('.js-viewer-slider-pagenum-now')?.textContent?.trim())||null,sliderLast:Number(document.querySelector('.js-viewer-slider-pagenum-last')?.textContent?.trim())||null,rect:{x:r.x,y:r.y,width:r.width,height:r.height},base:base,mapping:tiles,renderReady,clipUnsafe:s.clipUnsafe.has(id),unsafeSequence:s.unsafeSequence.get(c)??null,mutations:s.mutations.filter(x=>x.canvasId===id&&(!base||x.sequence>=base.sequence))};};
  const activeBody=()=>{const root=document.querySelector('section.viewer.js-viewer .image-container.js-viewer-content');if(!root)return {rows:[],sliderNow:null,sliderLast:null,colophon:false,complete:false,expectedAreaIndices:[],visibleBodyAreaIndices:[],reason:'missing_viewer'};const areas=[...root.querySelectorAll('.page-area.js-page-area')],allCanvases=[...root.querySelectorAll('canvas.page-image.js-page-image')];const now=Number(document.querySelector('.js-viewer-slider-pagenum-now')?.textContent?.trim()),last=Number(document.querySelector('.js-viewer-slider-pagenum-last')?.textContent?.trim());const isBack=a=>[...a.children].filter(p=>p.classList.contains('page')&&p.classList.contains('js-page')&&p.classList.contains('back-link-page')&&p.classList.contains('js-link-page')&&p.classList.contains('js-back-link-page')).length===1;const isAd=a=>[...a.children].filter(p=>p.classList.contains('page')&&p.classList.contains('js-page')&&p.classList.contains('js-page-ad')).length===1;const isTail=a=>a.id==='viewer-colophon'||a.classList.contains('back-matter-area')||isBack(a)||isAd(a);const firstTail=areas.findIndex(isTail);const firstBody=areas.findIndex(a=>a.querySelector('canvas.page-image.js-page-image'));const layouts=Number.isFinite(last)?[{name:'legacy-tail',body:last-4,back:last-3,ad:last-2,colophon:last-1},{name:'leading-area-tail',body:last-3,back:last-2,ad:last-1,colophon:last}]:[];const layoutFor=x=>{const back=areas[x.back],ad=areas[x.ad],colophon=areas[x.colophon];return !!back&&!!ad&&!!colophon&&isBack(back)&&isAd(ad)&&colophon.id==='viewer-colophon'};const layout=layouts.find(x=>layoutFor(x)&&x.body>=0&&firstBody>=0&&firstBody<=x.body&&x.body<firstTail)||null;const bodyIndices=layout?Array.from({length:layout.body-firstBody+1},(_,n)=>firstBody+n):[];const visibleBody=bodyIndices.filter(i=>visible(areas[i]));let expected=[];let reason=null;if(!layout)reason='unknown_body_layout';else if(!Number.isFinite(now)||!Number.isFinite(last)||now<1||now>last)reason='invalid_slider';else if(now===1)expected=[firstBody];else {const candidates=layout.name==='legacy-tail'?[now-1,now]:[now,now+1];expected=candidates.filter(i=>bodyIndices.includes(i));if(!expected.length)reason='non_body_slider';}if(!reason&&(!expected.every(i=>bodyIndices.includes(i))||new Set(visibleBody).size!==new Set(expected).size||visibleBody.some(i=>!expected.includes(i))))reason='expected_body_area_not_visible_or_extra';const rows=[];if(!reason){for(const ai of expected){const cs=areas[ai].querySelectorAll('canvas.page-image.js-page-image');if(cs.length!==1){reason=cs.length===0?'body_canvas_missing':'body_canvas_count';break}const value=row(cs[0],areas);if(!value){reason='body_canvas_invisible_or_unsafe';break}value.canvasIndex=allCanvases.indexOf(cs[0]);rows.push(value)}}const complete=!reason&&expected.length>0&&expected.length<=${MAX_ROWS}&&rows.length===expected.length;if(!complete)return {rows:[],sliderNow:Number.isFinite(now)?now:null,sliderLast:Number.isFinite(last)?last:null,colophon:!!document.querySelector('#viewer-colophon')&&visible(document.querySelector('#viewer-colophon')),complete:false,expectedAreaIndices:expected,visibleBodyAreaIndices:visibleBody,reason:reason||'body_area_count'};rows.sort((a,b)=>b.rect.x-a.rect.x);return {rows,sliderNow:Number.isFinite(now)?now:null,sliderLast:Number.isFinite(last)?last:null,colophon:!!document.querySelector('#viewer-colophon')&&visible(document.querySelector('#viewer-colophon')),complete:true,expectedAreaIndices:expected,visibleBodyAreaIndices:visibleBody};};
  const b64=a=>{let out='',u=new Uint8Array(a);for(let i=0;i<u.length;i+=0x8000)out+=String.fromCharCode(...u.subarray(i,i+0x8000));return btoa(out)};
  window.__comicDaysProductionCapture={active:activeBody, snapshot:async ids=>{const out=[];for(const id of ids||[]){const im=s.imageRefs.get(Number(id));if(!im)continue;const url=im.currentSrc||im.src||'';if(!url.startsWith('blob:')||url.length>4096){out.push({id:Number(id),error:'source_not_blob'});continue}let timer=null;try{const controller=new AbortController();timer=setTimeout(()=>controller.abort(),4000);const r=await fetch(url,{signal:controller.signal});if(!r.ok){out.push({id:Number(id),error:'source_fetch'});continue}const length=Number(r.headers.get('content-length')||0);if(length>${MAX_SOURCE_BYTES}){out.push({id:Number(id),error:'source_too_large'});continue}const b=await r.arrayBuffer();if(b.byteLength>${MAX_SOURCE_BYTES}){out.push({id:Number(id),error:'source_too_large'});continue}out.push({id:Number(id),url,bytes:b64(b),type:r.headers.get('content-type')||im.type||null})}catch(e){out.push({id:Number(id),error:'source_unavailable'})}finally{if(timer!==null)clearTimeout(timer)}}return out},debug:()=>({draws:s.draws.length,mutations:s.mutations.length,images:s.imageRefs.size})};
})();
"""
COMICDAYS_CAPTURE_HOOK = COMICDAYS_CAPTURE_HOOK.replace("${MAX_ROWS}", str(MAX_ROWS)).replace("${MAX_SOURCE_BYTES}", str(MAX_SOURCE_BYTES))


def _safe_state(value: dict[str, Any]) -> bool:
    state = value.get("state") or {}
    return (
        isinstance(state, dict)
        and all(state.get(k) == v for k, v in {"a": 1, "b": 0, "c": 0, "d": 1, "e": 0, "f": 0}.items())
        and state.get("alpha") == 1
        and state.get("composite") == "source-over"
        and state.get("filter") == "none"
    )


def _grid_coverage(
    rectangles: list[tuple[int, int, int, int]],
    frame_width: int,
    frame_height: int,
) -> int | None:
    """Validate the observed four-column by four-row tile geometry."""

    if len(rectangles) != 16:
        return None
    widths = {rect[2] for rect in rectangles}
    heights = {rect[3] for rect in rectangles}
    if len(widths) != 1 or len(heights) != 1:
        return None
    tile_width, tile_height = next(iter(widths)), next(iter(heights))
    if tile_width <= 0 or tile_height <= 0:
        return None
    x_starts = sorted({rect[0] for rect in rectangles})
    y_starts = sorted({rect[1] for rect in rectangles})
    if len(x_starts) != 4 or len(y_starts) != 4 or x_starts[0] != 0 or y_starts[0] != 0:
        return None
    if any(right != left + tile_width for left, right in pairwise(x_starts)):
        return None
    if any(bottom != top + tile_height for top, bottom in pairwise(y_starts)):
        return None
    max_right = x_starts[-1] + tile_width
    if max_right > frame_width or y_starts[-1] + tile_height != frame_height:
        return None
    if {(rect[0], rect[1]) for rect in rectangles} != {
        (x, y) for x in x_starts for y in y_starts
    }:
        return None
    return max_right


def strict_canvas_sequence(row: dict[str, Any]) -> dict[str, Any] | None:
    """Validate one latest full-base generation and return its reconstruction plan."""
    base = row.get("base")
    draws = [base, *list(row.get("mapping") or [])] if isinstance(base, dict) else []
    if not draws or not all(isinstance(d, dict) for d in draws):
        return None
    if row.get("clipUnsafe") is True:
        return None
    width = int(row.get("canvasWidth") or base.get("canvasWidth") or 0)
    height = int(row.get("canvasHeight") or base.get("canvasHeight") or 0)
    source = base.get("source") or {}
    sw, sh = int(source.get("width") or 0), int(source.get("height") or 0)
    if width <= 0 or height <= 0 or (sw, sh) != (width, height) or len(base.get("args") or []) != 8:
        return None
    if base["args"] != [0, 0, sw, sh, 0, 0, width, height] or not _safe_state(base):
        return None
    base_sequence = base.get("sequence")
    if not isinstance(base_sequence, (int, float)) or isinstance(base_sequence, bool):
        return None
    unsafe_sequence = row.get("unsafeSequence")
    if (
        isinstance(unsafe_sequence, (int, float))
        and not isinstance(unsafe_sequence, bool)
        and unsafe_sequence >= base_sequence
    ):
        return None
    source_id, source_url = base.get("sourceId"), base.get("sourceUrl")
    if not source_id or not isinstance(source_url, str) or not source_url.startswith("blob:"):
        return None
    tiles: list[dict[str, Any]] = []
    for draw in draws[1:]:
        args = draw.get("args")
        if not isinstance(args, list) or len(args) != 8 or not all(isinstance(v, int) and not isinstance(v, bool) for v in args):
            return None
        sx, sy, tw, th, dx, dy, dw, dh = args
        if (dw <= 0 or dh <= 0 or dx + dw <= 0 or dy + dh <= 0 or dx >= width or dy >= height) and _safe_state(draw):
            # The viewer emits a safe, wholly outside spacer draw.  It cannot
            # affect pixels and is retained only as diagnostic evidence.
            continue
        if not _safe_state(draw) or draw.get("sourceId") != source_id or draw.get("sourceUrl") != source_url:
            return None
        if tw <= 0 or th <= 0 or (tw, th) != (dw, dh) or sx < 0 or sy < 0 or sx + tw > sw or sy + th > sh or dx < 0 or dy < 0 or dx + dw > width or dy + dh > height:
            return None
        tiles.append(draw)
    max_right = _grid_coverage(
        [tuple(draw["args"][4:8]) for draw in tiles], width, height
    )
    max_source_right = _grid_coverage(
        [tuple(draw["args"][0:4]) for draw in tiles], sw, sh
    )
    # Comic DAYS leaves only the observed narrow right edge untiled.
    if max_right is None or max_source_right is None:
        return None
    if width - max_right != sw - max_source_right or width - max_right < 0 or width - max_right > max(32, width // 4):
        return None
    mutations = row.get("mutations") or []
    if mutations:
        return None
    return {"width": width, "height": height, "source_id": source_id, "source_url": source_url, "tiles": tiles}


def reconstruct_png(source_bytes: bytes, plan: dict[str, Any]) -> CaptureResult | None:
    if len(source_bytes) > MAX_SOURCE_BYTES:
        return None
    try:
        source = Image.open(io.BytesIO(source_bytes)).convert("RGBA")
        if source.size != (plan["width"], plan["height"]):
            return None
        # The full-base draw is part of the observed generation; paste it first
        # so a 5px/7px untiled source edge is retained exactly.
        out = source.copy()
        for draw in plan["tiles"]:
            sx, sy, sw, sh, dx, dy, dw, dh = draw["args"]
            tile = source.crop((sx, sy, sx + sw, sy + sh))
            if (dw, dh) != tile.size:
                return None
            out.paste(tile, (dx, dy))
        buffer = io.BytesIO()
        out.save(buffer, format="PNG")
        return capture_png_bytes(buffer.getvalue())
    except Exception:  # noqa: BLE001 - unsafe source falls back to rendered capture
        return None


def _jpeg_header(data: bytes) -> dict[str, Any] | None:
    """Parse a complete JPEG header and scan boundary without decoding pixels."""

    if not data.startswith(b"\xff\xd8"):
        return None
    records: list[dict[str, Any]] = [{"marker": 0xD8, "payload": b""}]
    index = 2
    sof: dict[str, Any] | None = None
    scan_start: int | None = None
    eoi: int | None = None
    while index < len(data):
        if data[index] != 0xFF:
            return None
        marker_start = index
        while index < len(data) and data[index] == 0xFF:
            index += 1
        if index >= len(data):
            return None
        marker = data[index]
        index += 1
        if marker == 0x00:
            return None
        if marker == 0xD9:
            records.append({"marker": marker, "payload": b""})
            eoi = marker_start
            break
        if marker == 0xDA:
            if index + 2 > len(data):
                return None
            length = int.from_bytes(data[index : index + 2], "big")
            if length < 2 or index + length > len(data):
                return None
            payload = data[index + 2 : index + length]
            records.append({"marker": marker, "payload": payload})
            index += length
            scan_start = index
            break
        if marker == 0xD8 or 0xD0 <= marker <= 0xD7:
            records.append({"marker": marker, "payload": b""})
            continue
        if index + 2 > len(data):
            return None
        length = int.from_bytes(data[index : index + 2], "big")
        if length < 2 or index + length > len(data):
            return None
        payload = data[index + 2 : index + length]
        records.append({"marker": marker, "payload": payload})
        if marker in ({_JPEG_SOF_BASELINE} | _JPEG_SOF_PROGRESSIVE | {0xC1, 0xC3, 0xC5, 0xC7, 0xC9, 0xCB, 0xCD, 0xCF}):
            if len(payload) < 6:
                return None
            count = payload[5]
            if len(payload) != 6 + count * 3:
                return None
            sof = {
                "marker": marker,
                "precision": payload[0],
                "height": int.from_bytes(payload[1:3], "big"),
                "width": int.from_bytes(payload[3:5], "big"),
                "components": [
                    {
                        "id": payload[6 + n * 3],
                        "h": payload[7 + n * 3] >> 4,
                        "v": payload[7 + n * 3] & 0x0F,
                        "qt": payload[8 + n * 3],
                    }
                    for n in range(count)
                ],
            }
        index += length
    if scan_start is not None and eoi is None:
        position = scan_start
        while position < len(data):
            if data[position] != 0xFF:
                position += 1
                continue
            marker_start = position
            while position < len(data) and data[position] == 0xFF:
                position += 1
            if position >= len(data):
                return None
            marker = data[position]
            position += 1
            if marker == 0x00 or 0xD0 <= marker <= 0xD7:
                continue
            if marker == 0xD9:
                eoi = marker_start
                break
            # Baseline entropy may contain stuffed bytes and restart markers;
            # every other post-SOS marker is unsupported and fails closed.
            return None
    if scan_start is None or eoi is None or eoi < scan_start or eoi + 2 != len(data):
        return None
    if sof is None:
        return None
    return {"records": records, "sof": sof, "scan_start": scan_start, "eoi": eoi}


def _jpeg_dct_read(data: bytes) -> tuple[Any, Path]:
    import jpeglib  # type: ignore[import-not-found]

    with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as handle:
        path = Path(handle.name)
        handle.write(data)
    try:
        return jpeglib.read_dct(str(path)), path
    except BaseException:
        path.unlink(missing_ok=True)
        raise


def _jpeg_dct_write(dct: Any, arrays: dict[str, Any]) -> bytes:
    for name, array in arrays.items():
        getattr(dct, name)[...] = array
    # jpeglib's -1 sentinel copies the source quantization/component setup.
    dct.qt = -1
    with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as handle:
        path = Path(handle.name)
    try:
        dct.write_dct(str(path))
        return path.read_bytes()
    finally:
        path.unlink(missing_ok=True)


def _jpeg_marker_payloads(data: bytes, marker: int) -> list[bytes]:
    header = _jpeg_header(data)
    return [item["payload"] for item in header["records"] if item["marker"] == marker] if header else []


def _jpeg_normalize_writer_metadata(source: bytes, generated: bytes) -> bytes | None:
    """Remove only the one observed generated duplicate JFIF APP0 marker."""

    source_header = _jpeg_header(source)
    generated_header = _jpeg_header(generated)
    if not source_header or not generated_header:
        return None
    source_records = source_header["records"]
    generated_records = generated_header["records"]
    def equivalent(left: list[dict[str, Any]], right: list[dict[str, Any]]) -> bool:
        return len(left) == len(right) and all(
            a["marker"] == b["marker"]
            and (a["marker"] == 0xC4 or a["payload"] == b["payload"])
            for a, b in zip(left, right)
        )

    if equivalent(generated_records, source_records):
        return generated
    source_app0 = [item["payload"] for item in source_records if item["marker"] == 0xE0]
    candidates = [
        index for index, item in enumerate(generated_records)
        if index == 1
        and item["marker"] == 0xE0
        and item["payload"].startswith(b"JFIF\x00")
        and item["payload"] in source_app0
        and generated_records.count(item) == source_records.count(item) + 1
    ]
    for index in candidates:
        normalized_records = generated_records[:index] + generated_records[index + 1 :]
        if len(normalized_records) != len(source_records):
            continue
        if not equivalent(normalized_records, source_records):
            continue
        output = bytearray(b"\xff\xd8")
        for item in normalized_records[1:]:
            marker = item["marker"]
            payload = item["payload"]
            if marker in {0xD8, 0xD9} or 0xD0 <= marker <= 0xD7:
                output.extend((0xFF, marker))
            else:
                output.extend((0xFF, marker))
                output.extend((len(payload) + 2).to_bytes(2, "big"))
                output.extend(payload)
            if marker == 0xDA:
                scan_start = generated_header["scan_start"]
                eoi = generated_header["eoi"]
                output.extend(generated[scan_start:eoi])
                output.extend(b"\xff\xd9")
                break
        candidate = bytes(output)
        if _jpeg_header(candidate) is not None:
            return candidate
    return None


def reconstruct_jpeg(source_bytes: bytes, plan: dict[str, Any]) -> CaptureResult | None:
    """Reconstruct one verified Comic DAYS canvas in the JPEG coefficient domain."""

    if len(source_bytes) > MAX_SOURCE_BYTES or not isinstance(plan, dict):
        return None
    try:
        width = int(plan["width"])
        height = int(plan["height"])
        tiles = plan["tiles"]
        if width <= 0 or height <= 0 or not isinstance(tiles, list) or len(tiles) != 16:
            return None
        source_rectangles: list[tuple[int, int, int, int]] = []
        destination_rectangles: list[tuple[int, int, int, int]] = []
        for draw in tiles:
            args = draw["args"]
            if not isinstance(args, list) or len(args) != 8 or any(
                not isinstance(value, int) or isinstance(value, bool) for value in args
            ):
                return None
            sx, sy, sw, sh, dx, dy, dw, dh = args
            if (sw, sh, dw, dh) != (280, 400, 280, 400):
                return None
            if min(sx, sy, dx, dy) < 0 or sx + sw > width or sy + sh > height or dx + dw > width or dy + dh > height:
                return None
            source_rectangles.append((sx, sy, sw, sh))
            destination_rectangles.append((dx, dy, dw, dh))
        expected_rectangles = {
            (x, y, 280, 400)
            for y in range(0, 1600, 400)
            for x in range(0, 1120, 280)
        }
        if set(source_rectangles) != expected_rectangles or set(destination_rectangles) != expected_rectangles:
            return None
    except (KeyError, TypeError, ValueError):
        return None
    source_header = _jpeg_header(source_bytes)
    if not source_header:
        return None
    sof = source_header["sof"]
    if sof["marker"] != _JPEG_SOF_BASELINE or sof["precision"] != 8:
        return None
    if (sof["width"], sof["height"]) != (width, height):
        return None
    components = sof["components"]
    if len(components) not in {1, 3} or any((item["h"], item["v"]) != (1, 1) for item in components):
        return None
    try:
        import numpy as np
        source_dct, source_temp = _jpeg_dct_read(source_bytes)
    except (ImportError, OSError, ValueError):
        return None
    output_dct = None
    output_temp: Path | None = None
    try:
        dimensions = (int(source_dct.width), int(source_dct.height))
        factors = [tuple(int(value) for value in row) for row in source_dct.samp_factor.tolist()]
        if dimensions != (sof["width"], sof["height"]) or any(pair != (1, 1) for pair in factors):
            return None
        component_names = [name for name in ("Y", "Cb", "Cr") if getattr(source_dct, name, None) is not None]
        if len(component_names) != len(components):
            return None
        widths = [int(source_dct.width_in_blocks(i)) for i in range(len(component_names))]
        heights = [int(source_dct.height_in_blocks(i)) for i in range(len(component_names))]
        if len(set(widths)) != 1 or len(set(heights)) != 1:
            return None
        source_qt = np.array(source_dct.qt, copy=True)
        source_quant_tbl_no = source_dct.quant_tbl_no.tolist()
        source_sampling = source_dct.samp_factor.tolist()
        source_colorspace = getattr(source_dct, "jpeg_color_space", None)
        source_progressive = bool(getattr(source_dct, "progressive_mode", False))
        original = {name: np.array(getattr(source_dct, name), dtype=np.int16, copy=True) for name in component_names}
        expected = {name: array.copy() for name, array in original.items()}
        for draw in tiles:
            args = draw["args"]
            sx, sy, sw, sh, dx, dy, dw, dh = args
            if any(value % 8 for value in args) or (sw, sh) != (280, 400):
                return None
            bx, by, dbx, dby = sx // 8, sy // 8, dx // 8, dy // 8
            bw, bh = sw // 8, sh // 8
            for name in component_names:
                expected[name][dby : dby + bh, dbx : dbx + bw] = original[name][by : by + bh, bx : bx + bw]
        generated = _jpeg_dct_write(source_dct, expected)
        normalized = _jpeg_normalize_writer_metadata(source_bytes, generated)
        if normalized is None:
            return None
        output_dct, output_temp = _jpeg_dct_read(normalized)
        observed = {name: np.array(getattr(output_dct, name), dtype=np.int16, copy=True) for name in component_names}
        if any(not np.array_equal(expected[name], observed[name]) for name in component_names):
            return None
        if not np.array_equal(source_qt, output_dct.qt):
            return None
        if source_quant_tbl_no != output_dct.quant_tbl_no.tolist():
            return None
        if source_sampling != output_dct.samp_factor.tolist():
            return None
        if source_colorspace != getattr(output_dct, "jpeg_color_space", None):
            return None
        if source_progressive != bool(getattr(output_dct, "progressive_mode", False)):
            return None
        normalized_header = _jpeg_header(normalized)
        if not normalized_header or normalized_header["sof"] != source_header["sof"]:
            return None
        edge_block = max(int(draw["args"][4]) + int(draw["args"][6]) for draw in plan["tiles"]) // 8
        if any(not np.array_equal(original[name][:, edge_block:], observed[name][:, edge_block:]) for name in component_names):
            return None
        return CaptureResult(data=normalized, width=dimensions[0], height=dimensions[1], mime_type="image/jpeg", file_extension=".jpg")
    except (AttributeError, IndexError, KeyError, OSError, ValueError, RuntimeError, TypeError):
        return None
    finally:
        if output_dct is not None:
            output_dct.close()
        source_dct.close()
        source_temp.unlink(missing_ok=True)
        if output_temp is not None:
            output_temp.unlink(missing_ok=True)
def source_id_for_row(row: dict[str, Any]) -> int | str | None:
    base = row.get("base")
    return base.get("sourceId") if isinstance(base, dict) else None
