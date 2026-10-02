"""Site-local Comic DAYS canvas provenance and native PNG reconstruction."""

from __future__ import annotations

import io
from itertools import pairwise
from typing import Any

from PIL import Image

from screenshot_crawler.core.capture import CaptureResult, capture_png_bytes

MAX_SOURCE_BYTES = 2_000_000
MAX_ROWS = 4

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
  const visible=e=>{if(!e)return false;const r=e.getBoundingClientRect();const a=Math.max(0,Math.min(r.right,innerWidth)-Math.max(r.left,0))*Math.max(0,Math.min(r.bottom,innerHeight)-Math.max(r.top,0));return r.width>0&&r.height>0&&a/(r.width*r.height)>=.5};
  const row=(c,areas)=>{const area=c.closest('.page-area.js-page-area');const ai=areas.indexOf(area);if(ai<0)return null;const r=c.getBoundingClientRect();if(!visible(c))return null;const id=canvas(c);const all=s.draws.filter(x=>x.canvasId===id);const safe=x=>{const q=x.state||{};return q.a===1&&q.b===0&&q.c===0&&q.d===1&&q.e===0&&q.f===0&&q.alpha===1&&q.composite==='source-over'&&q.filter==='none'};const full=x=>x.args?.length===8&&x.args[0]===0&&x.args[1]===0&&x.args[2]===x.source.width&&x.args[3]===x.source.height&&x.args[4]===0&&x.args[5]===0&&x.args[6]===x.canvasWidth&&x.args[7]===x.canvasHeight;
    const bases=all.filter(full);const base=bases.at(-1);const draws=base?all.filter(x=>x.sequence>=base.sequence):all;const tiles=draws.filter(x=>x!==base);
    const exactUnion=(rects,w,h)=>{if(rects.length!==16||rects.some(x=>x.some(v=>!Number.isInteger(v))))return null;const widths=[...new Set(rects.map(x=>x[2]))],heights=[...new Set(rects.map(x=>x[3]))];if(widths.length!==1||heights.length!==1||widths[0]<=0||heights[0]<=0)return null;const xs=[...new Set(rects.map(x=>x[0]))].sort((a,b)=>a-b),ys=[...new Set(rects.map(x=>x[1]))].sort((a,b)=>a-b);if(xs.length!==4||ys.length!==4||xs[0]!==0||ys[0]!==0)return null;for(let i=1;i<4;i++){if(xs[i]!==xs[i-1]+widths[0]||ys[i]!==ys[i-1]+heights[0])return null}const maxX=xs[3]+widths[0];if(maxX>w||ys[3]+heights[0]!==h)return null;const pairs=new Set(rects.map(x=>`${x[0]}:${x[1]}`));for(const x of xs)for(const y of ys)if(!pairs.has(`${x}:${y}`))return null;return {maxX};};
    const outside=x=>{const a=x.args||[];return a.length===8&&(a[4]+a[6]<=0||a[5]+a[7]<=0||a[4]>=x.canvasWidth||a[5]>=x.canvasHeight)};
    const usable=tiles.filter(x=>!outside(x));
    const valid=!!base&&safe(base)&&usable.length>0&&usable.every(x=>safe(x)&&Array.isArray(x.args)&&x.args.length===8&&x.args.every(Number.isFinite)&&x.args[2]===x.args[6]&&x.args[3]===x.args[7]&&x.args[2]>0&&x.args[3]>0&&x.args[0]>=0&&x.args[1]>=0&&x.args[0]+x.args[2]<=base.source.width&&x.args[1]+x.args[3]<=base.source.height&&x.args[4]>=0&&x.args[5]>=0&&x.args[4]+x.args[6]<=x.canvasWidth&&x.args[5]+x.args[7]<=x.canvasHeight);
    const dest=valid?exactUnion(usable.map(x=>x.args.slice(4,8)),base.canvasWidth,base.canvasHeight):null;const src=valid?exactUnion(usable.map(x=>x.args.slice(0,4)),base.source.width,base.source.height):null;const latest=usable.length?Math.max(...usable.map(x=>x.sequence)):base?.sequence;const clipDuring=!!base&&s.clipUnsafe.has(id)&&Number(s.clipSequence.get(id))<=Number(latest);const renderReady=!!base&&!!dest&&!!src&&!clipDuring&&(base.canvasWidth-dest.maxX===base.source.width-src.maxX);return {areaIndex:ai,canvasId:id,probeId:id,sliderNow:Number(document.querySelector('.js-viewer-slider-pagenum-now')?.textContent?.trim())||null,sliderLast:Number(document.querySelector('.js-viewer-slider-pagenum-last')?.textContent?.trim())||null,rect:{x:r.x,y:r.y,width:r.width,height:r.height},base:base,mapping:tiles,renderReady,clipUnsafe:s.clipUnsafe.has(id),unsafeSequence:s.unsafeSequence.get(c)??null,mutations:s.mutations.filter(x=>x.canvasId===id&&(!base||x.sequence>=base.sequence))};};
  const active=()=>{const root=document.querySelector('section.viewer.js-viewer .image-container.js-viewer-content');if(!root)return {rows:[],sliderNow:null,sliderLast:null,colophon:false};const areas=[...root.querySelectorAll('.page-area.js-page-area')],allCanvases=[...root.querySelectorAll('canvas.page-image.js-page-image')];const now=Number(document.querySelector('.js-viewer-slider-pagenum-now')?.textContent?.trim());const last=Number(document.querySelector('.js-viewer-slider-pagenum-last')?.textContent?.trim());const wanted=new Set([now-1,now]);const rows=[];for(const ai of wanted){const a=areas[ai];if(!a||a.id==='viewer-colophon')continue;const cs=a.querySelectorAll('canvas.page-image.js-page-image');if(cs.length===1){const value=row(cs[0],areas);if(value){value.canvasIndex=allCanvases.indexOf(cs[0]);rows.push(value)}}}rows.sort((a,b)=>b.rect.x-a.rect.x);const c=document.querySelector('#viewer-colophon');return {rows:rows.slice(0,${MAX_ROWS}),sliderNow:Number.isFinite(now)?now:null,sliderLast:Number.isFinite(last)?last:null,colophon:!!c&&visible(c)};};
  const b64=a=>{let out='',u=new Uint8Array(a);for(let i=0;i<u.length;i+=0x8000)out+=String.fromCharCode(...u.subarray(i,i+0x8000));return btoa(out)};
  window.__comicDaysProductionCapture={active, snapshot:async ids=>{const out=[];for(const id of ids||[]){const im=s.imageRefs.get(Number(id));if(!im)continue;const url=im.currentSrc||im.src||'';if(!url.startsWith('blob:')||url.length>4096){out.push({id:Number(id),error:'source_not_blob'});continue}let timer=null;try{const controller=new AbortController();timer=setTimeout(()=>controller.abort(),4000);const r=await fetch(url,{signal:controller.signal});if(!r.ok){out.push({id:Number(id),error:'source_fetch'});continue}const length=Number(r.headers.get('content-length')||0);if(length>${MAX_SOURCE_BYTES}){out.push({id:Number(id),error:'source_too_large'});continue}const b=await r.arrayBuffer();if(b.byteLength>${MAX_SOURCE_BYTES}){out.push({id:Number(id),error:'source_too_large'});continue}out.push({id:Number(id),url,bytes:b64(b),type:r.headers.get('content-type')||im.type||null})}catch(e){out.push({id:Number(id),error:'source_unavailable'})}finally{if(timer!==null)clearTimeout(timer)}}return out},debug:()=>({draws:s.draws.length,mutations:s.mutations.length,images:s.imageRefs.size})};
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
        if source.size != (plan["width"], plan["height"]): return None
        # The full-base draw is part of the observed generation; paste it first
        # so a 5px untiled source edge is retained exactly.
        out = source.copy()
        for draw in plan["tiles"]:
            sx, sy, sw, sh, dx, dy, dw, dh = draw["args"]
            tile = source.crop((sx, sy, sx + sw, sy + sh))
            if (dw, dh) != tile.size: return None
            out.paste(tile, (dx, dy))
        buffer = io.BytesIO(); out.save(buffer, format="PNG")
        return capture_png_bytes(buffer.getvalue())
    except Exception:  # noqa: BLE001 - unsafe source falls back to rendered capture
        return None


def source_id_for_row(row: dict[str, Any]) -> int | str | None:
    base = row.get("base")
    return base.get("sourceId") if isinstance(base, dict) else None
