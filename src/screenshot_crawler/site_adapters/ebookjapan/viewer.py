"""Small site-local DOM and compositor helpers for the ebookjapan Reader."""

from __future__ import annotations

import re
import unicodedata

COUNTER_SELECTOR = ".legacy-comic-footer__page-output"
TITLE_SELECTOR = ".legacy-comic-header__title"
SLOT_SELECTOR = ".comic-viewer__page-slot"
END_SELECTOR = ".next-item.book-last-dead-end__next"
MAX_SLOTS = 2_000
MAX_DRAW_CALLS = 20_000
MAX_PART_PIXELS = 2_000_000

_COUNTER = re.compile(r"^(\d+)\s*/\s*(\d+)$")


def normalize_title(value: str) -> str:
    return "".join(unicodedata.normalize("NFKC", value).split())


def parse_page_counter(value: str | None) -> tuple[int, int] | None:
    match = _COUNTER.fullmatch((value or "").strip())
    if match is None:
        return None
    current, total = int(match.group(1)), int(match.group(2))
    if current < 1 or total < current:
        return None
    return current, total


CAPTURE_OBSERVER_JS = r"""(() => {
  const key='__ejCaptureObserver',statusKey='__ejCaptureObserverStatus';
  const status=value=>{try{window[statusKey]=value;}catch{}return value;};
  if(window.top!==window)return status({installed:false,reason:'not-top-frame'});
  if(window[key])return status({installed:false,reason:'already-installed'});
  const canvasProto=HTMLCanvasElement.prototype,contextProto=window.CanvasRenderingContext2D?.prototype;
  if(!contextProto)return status({installed:false,reason:'2d-context-unavailable'});
  const names=['getContext','drawImage','putImageData','clearRect','fillRect','strokeRect','fillText','strokeText','fill','stroke','clip','reset'];
  const contexts={'getContext':canvasProto,'drawImage':contextProto,'putImageData':contextProto,'clearRect':contextProto,
    'fillRect':contextProto,'strokeRect':contextProto,'fillText':contextProto,'strokeText':contextProto,'fill':contextProto,'stroke':contextProto,'clip':contextProto};
  const descriptors=Object.fromEntries(names.map(name=>[name,Object.getOwnPropertyDescriptor(contexts[name]||contextProto,name)]));
  descriptors.getTransform=Object.getOwnPropertyDescriptor(contextProto,'getTransform');
  const originals=Object.fromEntries([...names,'getTransform'].map(name=>[name,descriptors[name]?.value]));
  const native=fn=>{try{return typeof fn==='function'&&/\[native code\]/.test(Function.prototype.toString.call(fn));}catch{return false;}};
  const unavailable=[...names,'getTransform'].filter(name=>!descriptors[name]||typeof originals[name]!=='function'||!(descriptors[name].writable||descriptors[name].configurable)||!native(originals[name]));
  if(unavailable.length)return status({installed:false,reason:'native-descriptor-conflict',unavailable});
  const routeAllowed=()=>window.top===window&&location.hostname==='ebookjapan.yahoo.co.jp'&&/^\/viewer\/purchased\/B[0-9]+\/$/.test(location.pathname)&&!location.search&&!location.hash;
  const states=new WeakMap(),contextRefs=new WeakMap();
  const MAX_DRAW_CALLS=20000;
  let calls=0,overflow=false,metadataFailures=0;
  const stateFor=canvas=>{let state=states.get(canvas);if(!state){state={drawGeneration:0,successfulDraws:0,mutationCount:0,clipCalls:0,lastFullDraw:false,lastDraw:null,resetObserved:false,contextIs2d:false};states.set(canvas,state);}return state;};
  const drainMutations=()=>{try{for(const record of mutationObserver.takeRecords()){if(record.target instanceof HTMLCanvasElement){const state=stateFor(record.target);state.drawGeneration=0;state.mutationCount=0;state.lastFullDraw=false;state.lastDraw=null;state.resetObserved=true;}}}catch{metadataFailures+=1;}};
  const mutationObserver=new MutationObserver(records=>{for(const record of records){if(record.target instanceof HTMLCanvasElement){const state=stateFor(record.target);state.drawGeneration=0;state.mutationCount=0;state.lastFullDraw=false;state.lastDraw=null;state.resetObserved=true;}}});
  mutationObserver.observe(document,{subtree:true,attributes:true,attributeFilter:['width','height']});
  const fullGeometry=(receiver,args)=>{
    const source=args[0];let sw=null,sh=null,sx=0,sy=0,dx=null,dy=null,dw=null,dh=null,overload=args.length;
    if(source instanceof HTMLImageElement){sw=source.naturalWidth;sh=source.naturalHeight;}
    else if(source instanceof HTMLCanvasElement||source instanceof OffscreenCanvas){sw=source.width;sh=source.height;}
    else if(typeof ImageBitmap!=='undefined'&&source instanceof ImageBitmap){sw=source.width;sh=source.height;}
    else if(typeof VideoFrame!=='undefined'&&source instanceof VideoFrame){sw=source.displayWidth;sh=source.displayHeight;}
    if(args.length===3){dx=args[1];dy=args[2];dw=sw;dh=sh;}
    else if(args.length===5){dx=args[1];dy=args[2];dw=args[3];dh=args[4];}
    else if(args.length===9){sx=args[1];sy=args[2];sw=args[3];sh=args[4];dx=args[5];dy=args[6];dw=args[7];dh=args[8];}
    let transform=null;try{const m=Reflect.apply(originals.getTransform,receiver,[]);transform=[m.a,m.b,m.c,m.d,m.e,m.f];}catch{metadataFailures+=1;}
    const canvas=receiver.canvas,identityTransform=transform&&transform.every((v,i)=>Math.abs(v-[1,0,0,1,0,0][i])<1e-6);
    // Only the exact same-size three-argument transfer was observed on the
    // live selected page. Scaled/cropped overloads remain unproven.
    const sourceFull=args.length===3&&sx===0&&sy===0&&sw===canvas.width&&sh===canvas.height;
    const targetFull=args.length===3&&dx===0&&dy===0&&dw===canvas.width&&dh===canvas.height;
    const alpha=receiver.globalAlpha,composite=receiver.globalCompositeOperation;
    const eligible=sourceFull&&targetFull&&identityTransform&&alpha===1&&composite==='source-over';
    return {eligible,overload,sourceType:source?.constructor?.name||'unknown',sourceWidth:sw,sourceHeight:sh,
      sourceRect:[sx,sy,sw,sh],destRect:[dx,dy,dw,dh],targetWidth:canvas.width,targetHeight:canvas.height,
      transform,alpha,composite};
  };
  const wrap=(name,fn)=>function(...args){
    const active=routeAllowed()&&(name==='getContext'?this instanceof HTMLCanvasElement:this instanceof CanvasRenderingContext2D);
    if(!active)return Reflect.apply(originals[name],this,args);
    if(name==='drawImage')drainMutations();
    let result,didThrow=false,thrown;try{result=Reflect.apply(originals[name],this,args);}catch(error){didThrow=true;thrown=error;}
    try{if(calls<MAX_DRAW_CALLS){calls++;if(name==='getContext'){const state=stateFor(this);state.contextIs2d=!didThrow&&String(args[0]).toLowerCase()==='2d'&&result instanceof CanvasRenderingContext2D;if(state.contextIs2d)contextRefs.set(this,result);}
      else if(this.canvas instanceof HTMLCanvasElement){const state=stateFor(this.canvas);if(name==='clip'){state.clipCalls++;}
        else if(name==='drawImage'){if(!didThrow){state.drawGeneration++;state.successfulDraws++;state.mutationCount++;state.resetObserved=false;const geometry=fullGeometry(this,args);state.lastFullDraw=geometry.eligible&&state.clipCalls===0;state.lastDraw=geometry;}}
        else if(name==='reset'&&!didThrow){state.drawGeneration=0;state.mutationCount=0;state.clipCalls=0;state.lastFullDraw=false;state.lastDraw=null;state.resetObserved=true;}
        else if(!didThrow){state.mutationCount++;state.lastFullDraw=false;state.lastDraw={method:name,targetWidth:this.canvas.width,targetHeight:this.canvas.height};}}
    }else overflow=true;}catch{metadataFailures++;}
    if(didThrow)throw thrown;return result;
  };
  const wrappers={};for(const name of names){wrappers[name]=wrap(name,originals[name]);Object.defineProperty(contexts[name]||contextProto,name,{...descriptors[name],value:wrappers[name]});}
  const observer={isInstalled:()=>names.every(name=>(contexts[name]||contextProto)[name]===wrappers[name]),
    health(){return {installed:names.every(name=>(contexts[name]||contextProto)[name]===wrappers[name]),overflow,metadataFailures,callCount:calls};},
    statusFor(canvas){drainMutations();if(!(canvas instanceof HTMLCanvasElement))return null;const state=states.get(canvas);return state?{drawGeneration:state.drawGeneration,successfulDraws:state.successfulDraws,mutationCount:state.mutationCount,clipCalls:state.clipCalls,lastFullDraw:state.lastFullDraw,lastDraw:state.lastDraw,resetObserved:state.resetObserved,contextIs2d:state.contextIs2d,canvasWidth:canvas.width,canvasHeight:canvas.height,overflow,metadataFailures}:null;},
    stop(){mutationObserver.disconnect();const restored={};for(const name of names){restored[name]=false;const proto=contexts[name]||contextProto;if(proto[name]===wrappers[name]){Object.defineProperty(proto,name,descriptors[name]);restored[name]=proto[name]===originals[name];}}status({installed:false,stopped:true,restored});return {restored,callCount:calls,overflow,metadataFailures};}};
  window[key]=observer;return status({installed:true,maxCalls:MAX_DRAW_CALLS,otherPixelMutationCoverage:'partial',clipState:'tracked-conservatively'});
})();"""


ANCHOR_READER_JS = r"""({expectedTitle,expectedPath,maxSlots})=>{
  const host='ebookjapan.yahoo.co.jp';
  const route=/^\/viewer\/purchased\/B[0-9]+\/$/.test(location.pathname)&&location.pathname===expectedPath&&location.hostname===host&&!location.search&&!location.hash;
  const slots=[...document.querySelectorAll('.comic-viewer__page-slot')];
  const counterText=(document.querySelector('.legacy-comic-footer__page-output')?.innerText||'').trim();
  const match=counterText.match(/^(\d+)\s*\/\s*(\d+)$/),counter=match?{current:Number(match[1]),total:Number(match[2])}:null;
  const titleNode=document.querySelector('.legacy-comic-header__title'),title=(titleNode?.innerText||titleNode?.textContent||'').trim();
  const layout=document.querySelector('.comic-viewer__scroll-container');
  const weak=new WeakMap(),ids=slots.map((slot,index)=>{weak.set(slot,index+1);return index+1;});
  const good=route&&normalize(expectedTitle)===normalize(title)&&counter&&counter.total===slots.length&&slots.length>0&&slots.length<=maxSlots
    &&new Set(slots).size===slots.length&&layout?.classList.contains('comic-viewer__scroll-container--horizontal-rtl')
    &&layout?.classList.contains('comic-viewer__scroll-container--spread');
  if(!good)return {ok:false,route,total:counter?.total??null,slotCount:slots.length,titleMatches:normalize(expectedTitle)===normalize(title),layoutSupported:!!layout?.classList.contains('comic-viewer__scroll-container--horizontal-rtl')&&!!layout?.classList.contains('comic-viewer__scroll-container--spread')};
  window.__ejReaderAnchor={document,pathname:location.pathname,title:normalize(expectedTitle),total:counter.total,slots,weak,ids,layout,canvasWeak:new WeakMap(),nextCanvasId:0};
  return {ok:true,current:counter.current,total:counter.total,slotCount:slots.length,uniqueIds:new Set(ids).size===slots.length,layoutSupported:true};
  function normalize(value){return String(value||'').normalize('NFKC').replace(/\s+/g,'');}
}"""


FRAME_STATE_JS = r"""({expectedCurrent})=>{
  const a=window.__ejReaderAnchor,o=window.__ejCaptureObserver;
  const normalize=value=>String(value||'').normalize('NFKC').replace(/\s+/g,'');
  const visible=e=>{if(!e||!e.isConnected||e.getClientRects().length===0)return false;for(let n=e;n;n=n.parentElement){const s=getComputedStyle(n);if(n.hidden||s.display==='none'||s.visibility==='hidden'||s.visibility==='collapse'||Number(s.opacity)===0)return false;}return true;};
  const rect=e=>{const r=e.getBoundingClientRect();return {left:r.left,right:r.right,top:r.top,bottom:r.bottom,width:r.width,height:r.height,viewport:r.right>0&&r.left<innerWidth&&r.bottom>0&&r.top<innerHeight};};
  const paintsColor=value=>{
    if(!value||value==='transparent')return false;
    const match=value.match(/rgba?\(([^)]+)\)/i);
    if(!match)return true;
    const fields=match[1].split(/[,\s/]+/).filter(Boolean);
    return fields.length<4||Number(fields[fields.length-1])>0;
  };
  const hasPaintRisk=element=>{
    const s=getComputedStyle(element);
    if(Number(s.opacity)!==1||s.filter!=='none'||s.backdropFilter!=='none'||s.mixBlendMode!=='normal'
      ||s.clipPath!=='none'||s.maskImage!=='none'||s.backgroundImage!=='none'||paintsColor(s.backgroundColor)
      ||s.boxShadow!=='none'||s.textShadow!=='none'||(s.outlineStyle!=='none'&&paintsColor(s.outlineColor)))return true;
    if((Number.parseFloat(s.borderTopWidth)>0&&paintsColor(s.borderTopColor))
      ||(Number.parseFloat(s.borderRightWidth)>0&&paintsColor(s.borderRightColor))
      ||(Number.parseFloat(s.borderBottomWidth)>0&&paintsColor(s.borderBottomColor))
      ||(Number.parseFloat(s.borderLeftWidth)>0&&paintsColor(s.borderLeftColor)))return true;
    if((element.textContent||'').trim()&&paintsColor(s.color))return true;
    if(element.matches('img,canvas,svg,video,iframe')||element.querySelector('img,canvas,svg,video,iframe'))return true;
    for(const pseudo of ['::before','::after']){
      const p=getComputedStyle(element,pseudo);
      if(p.content&&p.content!=='none'&&p.content!=='normal')return true;
    }
    return false;
  };
  const hasOutsetPaintRisk=element=>{
    const s=getComputedStyle(element);
    // These effects can paint outside getBoundingClientRect(). Refuse them
    // before the border-box intersection test, including pointer-events:none
    // hosts whose generated content or shadow reaches the selected canvas.
    if(s.filter!=='none'||s.backdropFilter!=='none'||s.boxShadow!=='none'
      ||s.textShadow!=='none'||(s.outlineStyle!=='none'&&paintsColor(s.outlineColor)))return true;
    for(const pseudo of ['::before','::after']){
      const p=getComputedStyle(element,pseudo);
      if(p.content&&p.content!=='none'&&p.content!=='normal')return true;
    }
    return false;
  };
  const captureSurfaceReason=canvas=>{
    const r=canvas.getBoundingClientRect(),style=getComputedStyle(canvas);
    if(r.left < -0.5 || r.top < -0.5 || r.right > innerWidth+0.5 || r.bottom > innerHeight+0.5) return 'outside-viewport';
    if(hasOutsetPaintRisk(canvas))return 'canvas-outset-paint';
    if(style.transform!=='none'||style.clipPath!=='none'||style.maskImage!=='none'||Number(style.opacity)!==1
      ||style.filter!=='none'||style.mixBlendMode!=='normal'||style.backgroundImage!=='none'||paintsColor(style.backgroundColor)) return 'canvas-compositing-style';
    const ancestors=new Set();
    for(let node=canvas.parentElement;node;node=node.parentElement){
      ancestors.add(node);
      const s=getComputedStyle(node),box=node.getBoundingClientRect();
      if(hasOutsetPaintRisk(node))return 'ancestor-outset-paint';
      if(s.clipPath!=='none'||s.maskImage!=='none'||s.transform!=='none'||Number(s.opacity)!==1
        ||s.filter!=='none'||s.backdropFilter!=='none'||s.mixBlendMode!=='normal') return 'ancestor-compositing-style';
      for(const pseudo of ['::before','::after']){
        const p=getComputedStyle(node,pseudo);
        if(p.content&&p.content!=='none'&&p.content!=='normal')return 'ancestor-pseudo-element';
      }
      const clipX=['hidden','clip','scroll','auto'].includes(s.overflowX),clipY=['hidden','clip','scroll','auto'].includes(s.overflowY);
      const left=box.left+node.clientLeft,top=box.top+node.clientTop,right=left+node.clientWidth,bottom=top+node.clientHeight;
      if((clipX&&(r.left<left-0.5||r.right>right+0.5))||(clipY&&(r.top<top-0.5||r.bottom>bottom+0.5))) return 'ancestor-overflow-clip';
    }
    const all=document.querySelectorAll('*');
    if(all.length>20000)return 'dom-inventory-limit';
    for(const element of all){
      if(element===canvas||ancestors.has(element)||canvas.contains(element)||!visible(element))continue;
      if(hasOutsetPaintRisk(element))return 'outset-painted-element:'+element.tagName.toLowerCase();
      const o=element.getBoundingClientRect();
      if(o.right<=r.left||o.left>=r.right||o.bottom<=r.top||o.top>=r.bottom)continue;
      if(hasPaintRisk(element))return 'intersecting-painted-element:'+element.tagName.toLowerCase();
    }
    for(const fy of [0.1,0.3,0.5,0.7,0.9]) for(const fx of [0.1,0.3,0.5,0.7,0.9]){
      const x=r.left+r.width*fx,y=r.top+r.height*fy,top=document.elementFromPoint(x,y);
      if(top!==canvas&&!canvas.contains(top)) return 'occluded-sample-point';
    }
    return null;
  };
  if(!o||typeof o.health!=='function'||o.health().installed!==true)return {status:'observer-unavailable'};
  const health=o.health();
  if(health.overflow===true)return {status:'observer-overflow'};
  if(health.metadataFailures!==0)return {status:'observer-metadata-failure'};
  if(!a||document!==a.document||location.pathname!==a.pathname||location.hostname!=='ebookjapan.yahoo.co.jp'||location.search||location.hash)return {status:'identity-mismatch'};
  const slots=[...document.querySelectorAll('.comic-viewer__page-slot')];
  if(slots.length!==a.slots.length||slots.some((slot,index)=>slot!==a.slots[index]))return {status:'slot-order-mismatch'};
  const layout=document.querySelector('.comic-viewer__scroll-container');
  if(layout!==a.layout||!layout?.classList.contains('comic-viewer__scroll-container--horizontal-rtl')||!layout?.classList.contains('comic-viewer__scroll-container--spread'))return {status:'layout-mismatch'};
  const titleNode=document.querySelector('.legacy-comic-header__title'),titleVisible=visible(titleNode);
  const title=titleVisible?normalize(titleNode.innerText||titleNode.textContent):null;
  if(titleVisible&&title!==a.title)return {status:'identity-mismatch'};
  const counterNode=document.querySelector('.legacy-comic-footer__page-output'),counterVisible=visible(counterNode);
  const counterText=counterVisible?(counterNode.innerText||counterNode.textContent||'').trim():'';
  const m=counterText.match(/^(\d+)\s*\/\s*(\d+)$/),counter=m?{current:Number(m[1]),total:Number(m[2])}:null;
  if(counter&&counter.total!==a.total)return {status:'counter-total-mismatch'};
  const parts=[],visibleSlots=[];let incomplete=false;
  for(let ordinal=0;ordinal<slots.length;ordinal++){
    const slot=slots[ordinal],sr=rect(slot);
    if(!visible(slot)||!sr.viewport)continue;
    const slotId=a.weak.get(slot);visibleSlots.push(slotId);
    const canvases=[...slot.querySelectorAll('canvas')].filter(canvas=>visible(canvas)&&rect(canvas).viewport&&canvas.width>=2&&canvas.height>=100);
    if(canvases.length!==1){incomplete=true;continue;}
    const canvas=canvases[0],cr=rect(canvas),draw=o?.statusFor(canvas)||null;
    let canvasId=a.canvasWeak.get(canvas);if(!canvasId){a.nextCanvasId+=1;canvasId=a.nextCanvasId;a.canvasWeak.set(canvas,canvasId);}
    const geometry=draw?.lastDraw,backingAspect=canvas.width/canvas.height,cssAspect=cr.width/cr.height;
    const aspectMatches=Number.isFinite(backingAspect)&&Number.isFinite(cssAspect)
      &&Math.abs(backingAspect-cssAspect)<=Math.max(0.01,cssAspect*0.02);
    const drawReady=!!draw&&draw.contextIs2d===true&&draw.drawGeneration>0&&draw.lastFullDraw===true
      &&draw.resetObserved===false&&draw.overflow===false&&draw.clipCalls===0&&geometry?.eligible===true
      &&geometry.targetWidth===canvas.width&&geometry.targetHeight===canvas.height&&aspectMatches;
    if(!drawReady)incomplete=true;
    const captureSurface=captureSurfaceReason(canvas);
    parts.push({slotId,slotOrdinal:ordinal,canvasId,canvasIndex:[...slot.querySelectorAll('canvas')].indexOf(canvas),backingWidth:canvas.width,backingHeight:canvas.height,
      cssRect:cr,captureSurfaceSafe:captureSurface===null,captureSurfaceReason:captureSurface,backingAspect,cssAspect,drawGeneration:draw?.drawGeneration??null,successfulDraws:draw?.successfulDraws??null,mutationCount:draw?.mutationCount??null,clipCalls:draw?.clipCalls??null,
      lastFullDraw:draw?.lastFullDraw??false,resetObserved:draw?.resetObserved??true,contextIs2d:draw?.contextIs2d??false,observerOverflow:draw?.overflow??true,drawReady});
  }
  parts.sort((left,right)=>right.cssRect.left-left.cssRect.left);
  const headerVisible=titleVisible;
  const dead=[...document.querySelectorAll('.next-item.book-last-dead-end__next')].filter(visible).map(element=>{const r=rect(element),text=normalize(element.innerText||element.textContent);const controls=[...element.querySelectorAll('a,button,[role="button"]')].filter(visible).length;return {text,rect:r,controls};});
  const deadVisible=dead.some(item=>item.rect.viewport&&item.controls===0&&item.text==='\u3053\u306e\u4f5c\u54c1\u306f\u3053\u3053\u307e\u3067\u3067\u3059');
  const visibleActions=[...document.querySelectorAll('a,button,[role="button"]')].filter(visible).filter(e=>rect(e).viewport).length;
  if(parts.length===0&&deadVisible)return {status:'end',routeStable:true,slotCount:slots.length,visibleSlots,parts:[],deadEnd:dead,visibleActions,toolbarVisible:headerVisible||counterVisible};
  if(parts.length===0&&dead.some(item=>item.rect.viewport))return {status:'unknown-terminal-marker',routeStable:true,slotCount:slots.length,visibleSlots,parts:[],deadEnd:dead,visibleActions,toolbarVisible:headerVisible||counterVisible};
  const current=counter?.current??expectedCurrent;
  if(parts.length===0)return {status:'loading',routeStable:true,slotCount:slots.length,visibleSlots,parts:[],deadEnd:dead,toolbarVisible:headerVisible||counterVisible};
  const expectedParts=current===1?1:2;
  if(incomplete||parts.length!==expectedParts)return {status:'partial',routeStable:true,slotCount:slots.length,visibleSlots,parts,deadEnd:dead,toolbarVisible:headerVisible||counterVisible,current};
  return {status:'content',routeStable:true,slotCount:slots.length,visibleSlots,parts,deadEnd:dead,toolbarVisible:headerVisible||counterVisible,
    counter,title,counterVisible:!!counter&&counterVisible,viewport:{width:innerWidth,height:innerHeight}};
}"""
