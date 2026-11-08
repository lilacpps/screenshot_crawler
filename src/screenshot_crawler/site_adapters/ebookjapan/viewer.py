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


NAVIGATION_TARGET_JS = r"""({x,capturedParts})=>{
  const a=window.__ejReaderAnchor;
  const observer=window.__ejCaptureObserver;
  const classes=e=>typeof e?.className==='string'?[...e.classList].filter(x=>/^[A-Za-z0-9_-]{1,80}$/.test(x)).slice(0,8):[];
  const rect=e=>{const r=e.getBoundingClientRect();return {left:r.left,right:r.right,top:r.top,bottom:r.bottom,width:r.width,height:r.height};};
  const visible=e=>{if(!e||!e.isConnected||e.getClientRects().length===0)return false;for(let n=e;n;n=n.parentElement){const s=getComputedStyle(n);if(n.hidden||s.display==='none'||s.visibility==='hidden'||s.visibility==='collapse'||Number(s.opacity)===0)return false;}return true;};
  const sameArray=(left,right)=>Array.isArray(left)&&Array.isArray(right)&&left.length===right.length&&left.every((value,index)=>value===right[index]);
  const partMatches=expected=>{
    if(!expected||!Number.isInteger(expected.slotOrdinal)||!Number.isInteger(expected.slotId)||!Number.isInteger(expected.canvasIndex))return false;
    const slot=a?.slots?.[expected.slotOrdinal],canvas=slot?.querySelectorAll('canvas')[expected.canvasIndex];
    if(!slot||slot!==slots[expected.slotOrdinal]||a.weak.get(slot)!==expected.slotId||!canvas
      ||a.canvasWeak.get(canvas)!==expected.canvasId||canvas.width!==expected.backingWidth||canvas.height!==expected.backingHeight)return false;
    const r=canvas.getBoundingClientRect(),expectedRect=expected.cssRect;
    if(!expectedRect||['left','right','top','bottom','width','height'].some(key=>r[key]!==expectedRect[key])
      ||(r.right>0&&r.left<innerWidth&&r.bottom>0&&r.top<innerHeight)!==expectedRect.viewport)return false;
    const state=observer?.statusFor?.(canvas),geometry=state?.lastDraw,expectedGeometry=expected.drawGeometry;
    const geometryKeys=['eligible','overload','sourceType','sourceWidth','sourceHeight','targetWidth','targetHeight','alpha','composite'];
    const geometryMatches=!!geometry&&!!expectedGeometry&&geometryKeys.every(key=>geometry[key]===expectedGeometry[key])
      &&sameArray(geometry.sourceRect,expectedGeometry.sourceRect)&&sameArray(geometry.destRect,expectedGeometry.destRect)
      &&sameArray(geometry.transform,expectedGeometry.transform);
    const cssAspect=r.width/r.height,backingAspect=canvas.width/canvas.height;
    const aspectMatches=Number.isFinite(cssAspect)&&Number.isFinite(backingAspect)&&Math.abs(backingAspect-cssAspect)<=Math.max(0.01,cssAspect*0.02);
    const ready=!!state&&state.contextIs2d===true&&state.drawGeneration>0&&state.lastFullDraw===true
      &&state.resetObserved===false&&state.overflow===false&&state.metadataFailures===0&&state.clipCalls===0
      &&geometry?.eligible===true&&geometry.targetWidth===canvas.width&&geometry.targetHeight===canvas.height&&aspectMatches;
    return ready&&expected.drawReady===true&&geometryMatches
      &&state.drawGeneration===expected.drawGeneration&&state.successfulDraws===expected.successfulDraws
      &&state.mutationCount===expected.mutationCount&&state.clipCalls===expected.clipCalls
      &&state.lastFullDraw===expected.lastFullDraw&&state.resetObserved===expected.resetObserved
      &&state.contextIs2d===expected.contextIs2d&&state.overflow===expected.observerOverflow;
  };
  const titleNode=document.querySelector('.legacy-comic-header__title');
  const titleMatches=!titleNode||String(titleNode.innerText||titleNode.textContent||'').normalize('NFKC').replace(/\s+/g,'')===a?.title;
  const layout=document.querySelector('.comic-viewer__scroll-container');
  const slots=[...document.querySelectorAll('.comic-viewer__page-slot')];
  const slotsPinned=!!a&&document===a.document&&location.hostname==='ebookjapan.yahoo.co.jp'&&!location.search&&!location.hash
    &&location.pathname===a.pathname&&slots.length===a.slots.length&&slots.every((slot,index)=>slot===a.slots[index])
    &&layout===a.layout&&layout.classList.contains('comic-viewer__scroll-container--horizontal-rtl')
    &&layout.classList.contains('comic-viewer__scroll-container--spread')&&titleMatches;
  const expectedParts=Array.isArray(capturedParts)?capturedParts:[];
  const uniqueCapturedParts=expectedParts.length>=1&&expectedParts.length<=2
    &&new Set(expectedParts.map(part=>part?.slotId)).size===expectedParts.length;
  const partsMatch=uniqueCapturedParts&&expectedParts.every(partMatches);
  const observerHealth=observer?.health?.()||null;
  const capturedPartsMatch=partsMatch&&observerHealth?.installed===true
    &&observerHealth.overflow===false&&observerHealth.metadataFailures===0;
  const y=Math.floor(innerHeight/2);
  const hit=document.elementFromPoint(x,y),slot=hit?.closest('.comic-viewer__page-slot')||null;
  const slotId=slot&&a?.weak?a.weak.get(slot):null;
  const expected=Array.isArray(capturedParts)?capturedParts.find(part=>part&&part.slotId===slotId):null;
  const canvas=hit?.closest('canvas')||null,canvasId=canvas&&a?.canvasWeak?a.canvasWeak.get(canvas):null;
  const canvasMatches=!canvas||!!expected&&expected.canvasId===canvasId&&slot?.contains(canvas);
  const exactPageHit=hit===slot||!!canvas&&hit===canvas;
  const inPinnedSlot=!!slot&&layout?.contains(slot)&&!!expected&&canvasMatches&&exactPageHit&&slot===a.slots[slotId-1];
  let interactive=false,blocked=false,insideSlot=false;
  for(let node=hit;node;node=node.parentElement){
    if(node.matches?.('a,button,[role="button"],input,select,textarea,[contenteditable="true"]'))interactive=true;
    if(node.matches?.('dialog,[role="dialog"],[aria-modal="true"],.intro-modal,.book-last,.next-item,.book-last-dead-end__next,.book-last__cta'))blocked=true;
    if(node===slot)insideSlot=true;
  }
  const modalVisible=[...document.querySelectorAll('dialog,[role="dialog"],[aria-modal="true"],.intro-modal')].some(e=>visible(e)&&(()=>{const r=rect(e);return r.right>0&&r.left<innerWidth&&r.bottom>0&&r.top<innerHeight;})());
  const r=hit?rect(hit):null;
  return {safe:slotsPinned&&capturedPartsMatch&&inPinnedSlot&&insideSlot&&!interactive&&!blocked&&!modalVisible,
    slotsPinned,capturedPartsMatch,inPinnedSlot,insideSlot,interactive,blocked,modalVisible,slotId:typeof slotId==='number'?slotId:null,
    canvasId:typeof canvasId==='number'?canvasId:null,targetTag:hit?.tagName||null,targetClasses:classes(hit),
    targetRect:r,viewport:{width:innerWidth,height:innerHeight},x,y};
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
  const strictFinitePx=value=>{
    if(typeof value!=='string')return null;
    const match=/^(-?(?:\d+(?:\.\d+)?|\.\d+))px$/.exec(value.trim());
    if(!match)return null;
    const parsed=Number(match[1]);return Number.isFinite(parsed)?parsed:null;
  };
  const zeroBorderImageOutset=value=>typeof value==='string'&&value.trim().split(/\s+/).length>=1
    &&value.trim().split(/\s+/).every(part=>/^0(?:\.0+)?(?:px)?$/.test(part));
  const supportedPure2dTranslation=value=>{
    if(value==='none')return true;
    try{
      const matrix=new DOMMatrixReadOnly(value);
      return matrix.is2D&&matrix.a===1&&matrix.b===0&&matrix.c===0&&matrix.d===1
        &&Number.isFinite(matrix.e)&&Number.isFinite(matrix.f);
    }catch{return false;}
  };
  const supportedTranslate=value=>{
    if(value==='none')return true;
    const parts=typeof value==='string'?value.trim().split(/\s+/):[];
    return parts.length>=1&&parts.length<=2&&parts.every(part=>strictFinitePx(part)!==null);
  };
  const hasUnsupportedOutlineImageTransform=element=>{
    let depth=0,reachedDocumentElement=false;
    for(let node=element;node;node=node.parentElement){
      depth+=1;if(depth>64)return true;
      if(!(node instanceof HTMLElement)||node.namespaceURI!=='http://www.w3.org/1999/xhtml')return true;
      const style=getComputedStyle(node);
      if(!supportedPure2dTranslation(style.transform)||!supportedTranslate(style.translate)
        ||style.rotate!=='none'||style.scale!=='none'||style.zoom!=='1'
        ||style.perspective!=='none'||style.transformStyle==='preserve-3d'
        ||style.offsetPath!=='none'||style.offsetDistance!=='0px'
        ||style.offsetRotate!=='auto 0deg'||style.offsetAnchor!=='auto'
        ||style.filter!=='none'||style.backdropFilter!=='none'||style.boxShadow!=='none'
        ||style.textShadow!=='none'||style.borderImageSource!=='none'
        ||!zeroBorderImageOutset(style.borderImageOutset)
        ||style.getPropertyValue('-webkit-box-reflect')!=='none'
        ||(node!==element&&style.outlineStyle!=='none'&&paintsColor(style.outlineColor)))return true;
      for(const pseudo of ['::before','::after']){
        const pseudoStyle=getComputedStyle(node,pseudo);
        if(pseudoStyle.content&&pseudoStyle.content!=='none'&&pseudoStyle.content!=='normal')return true;
      }
      if(node===document.documentElement){reachedDocumentElement=true;break;}
    }
    return !reachedDocumentElement;
  };
  const finiteOutlineOnlyImageDisjointFromTarget=(element,targetRect)=>{
    if(!Number.isFinite(window.devicePixelRatio)||window.devicePixelRatio<1
      ||!(element instanceof HTMLImageElement)||element.namespaceURI!=='http://www.w3.org/1999/xhtml'
      ||!element.isConnected||!element.complete||element.naturalWidth<=0||element.naturalHeight<=0
      ||element.namespaceURI!=='http://www.w3.org/1999/xhtml'
      ||element.childNodes.length!==0||element.children.length!==0
      ||hasUnsupportedOutlineImageTransform(element))return false;
    const style=getComputedStyle(element);
    if(style.outlineStyle!=='solid'||style.filter!=='none'||style.backdropFilter!=='none'
      ||style.boxShadow!=='none'||style.textShadow!=='none'
      ||style.borderImageSource!=='none'||!zeroBorderImageOutset(style.borderImageOutset)
      ||style.getPropertyValue('-webkit-box-reflect')!=='none')return false;
    for(const pseudo of ['::before','::after']){
      const pseudoStyle=getComputedStyle(element,pseudo);
      if(pseudoStyle.content&&pseudoStyle.content!=='none'&&pseudoStyle.content!=='normal')return false;
    }
    const outlineWidth=strictFinitePx(style.outlineWidth),outlineOffset=strictFinitePx(style.outlineOffset);
    if(outlineWidth===null||outlineOffset===null||outlineWidth<0)return false;
    const clientRects=element.getClientRects();
    if(clientRects.length!==1)return false;
    const client=clientRects[0],box=element.getBoundingClientRect();
    const finitePositive=[box.left,box.top,box.right,box.bottom,box.width,box.height].every(Number.isFinite)
      &&box.width>0&&box.height>0;
    if(!finitePositive||![client.left,client.top,client.right,client.bottom,client.width,client.height].every(Number.isFinite)
      ||client.width<=0||client.height<=0
      ||['left','top','right','bottom','width','height'].some(key=>client[key]!==box[key]))return false;
    // Bound this supported Chromium image-outline case with a conservative 2 CSS px AA margin.
    // Equality/contact is unsafe; only strict separation from the target canvas is accepted.
    const expansion=outlineWidth+Math.abs(outlineOffset)+2;
    const expanded={left:box.left-expansion,top:box.top-expansion,
      right:box.right+expansion,bottom:box.bottom+expansion};
    if(!Object.values(expanded).every(Number.isFinite))return false;
    const strictlyDisjoint=expanded.right<targetRect.left||expanded.left>targetRect.right
      ||expanded.bottom<targetRect.top||expanded.top>targetRect.bottom;
    return strictlyDisjoint;
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
      if(hasOutsetPaintRisk(element)&&!finiteOutlineOnlyImageDisjointFromTarget(element,r))
        return 'outset-painted-element:'+element.tagName.toLowerCase();
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
      lastFullDraw:draw?.lastFullDraw??false,resetObserved:draw?.resetObserved??true,contextIs2d:draw?.contextIs2d??false,observerOverflow:draw?.overflow??true,drawReady,drawGeometry:geometry});
  }
  parts.sort((left,right)=>right.cssRect.left-left.cssRect.left);
  const headerVisible=titleVisible;
  const dead=[...document.querySelectorAll('.next-item.book-last-dead-end__next')].map(element=>{const r=rect(element),text=normalize(element.innerText||element.textContent);const controls=[...element.querySelectorAll('a,button,[role="button"]')].filter(visible).length;return {visible:visible(element),text,textExact:text==='\u3053\u306e\u4f5c\u54c1\u306f\u3053\u3053\u307e\u3067\u3067\u3059',rect:r,controls};});
  const actionable=[...document.querySelectorAll('a,button,[role="button"],input,select,textarea,[contenteditable="true"]')].filter(visible).filter(e=>rect(e).viewport);
  const visibleActions=actionable.length,actionInventoryCapped=visibleActions>256;
  const modalCount=[...document.querySelectorAll('dialog,[role="dialog"],[aria-modal="true"],.intro-modal')].filter(visible).filter(e=>rect(e).viewport).length;
  const pageCanvasCount=slots.reduce((count,slot)=>count+[...slot.querySelectorAll('canvas')].filter(canvas=>visible(canvas)&&rect(canvas).viewport&&canvas.width>=2&&canvas.height>=100).length,0);
  const isUnder=(element,root)=>!!element&&!!root&&root.contains(element);
  const terminal={profile:null,rootCount:0,innerCount:0,rootVisible:false,innerVisible:false,rootInViewport:false,innerInViewport:false,insidePinnedLayout:false,visibleSlotCount:visibleSlots.length,
    visiblePageCanvasCount:pageCanvasCount,visibleActionCount:visibleActions,actionInventoryCapped,modalCount,unknownActionCount:0,
    riskyActionCount:0,partition:{},moduleCounts:{},headerCounts:{},nativeCounterVisible:counterVisible,nativeCounter:counter};
  const angelRoots=[...document.querySelectorAll('.book-last-dead-end')];
  const angelMarkers=[...document.querySelectorAll('.next-item.book-last-dead-end__next')];
  const mudaRoots=[...document.querySelectorAll('.book-last')];
  const activeAngelRoot=angelRoots.some(element=>visible(element)&&rect(element).viewport);
  const activeAngelMarker=angelMarkers.some(element=>visible(element)&&rect(element).viewport);
  const activeMudaRoot=mudaRoots.some(element=>visible(element)&&rect(element).viewport);
  if(parts.length===0&&visibleSlots.length===0&&pageCanvasCount===0&&modalCount>0
    &&!activeAngelRoot&&!activeAngelMarker&&!activeMudaRoot){
    return {status:'unknown-terminal-marker',routeStable:true,slotCount:slots.length,visibleSlots,parts:[],deadEnd:dead,
      visibleActions,toolbarVisible:headerVisible||counterVisible,terminal:{...terminal,profile:'unknown-modal'}};
  }
  if(parts.length===0&&visibleSlots.length===0&&pageCanvasCount===0&&(activeAngelRoot||activeAngelMarker)){
    terminal.rootCount=angelRoots.length;
    const root=angelRoots.length===1?angelRoots[0]:null;
    const inners=root?[...root.querySelectorAll(':scope > .book-last-dead-end__inner')]:[];
    terminal.innerCount=inners.length;
    const inner=inners.length===1?inners[0]:null;
    terminal.rootVisible=!!root&&visible(root);terminal.innerVisible=!!inner&&visible(inner);
    terminal.rootInViewport=!!root&&rect(root).viewport;terminal.innerInViewport=!!inner&&rect(inner).viewport;
    const shell=root?.parentElement?.matches('.viewer-last-shell')?root.parentElement:null;
    const lastCell=shell?.parentElement?.matches('.viewer-liber__viewer-last-cell')?shell.parentElement:null;
    const customCell=lastCell?.parentElement?.matches('.comic-viewer__custom-cell--interactive')?lastCell.parentElement:null;
    terminal.shellChainValid=!!root&&!!shell&&!!lastCell&&!!customCell&&customCell.contains(root);
    terminal.insidePinnedLayout=terminal.shellChainValid&&isUnder(customCell,layout);
    const modules={review:inner?[...inner.children].filter(e=>e.matches('.review-module.book-last-dead-end__review')):[],
      coupon:inner?[...inner.children].filter(e=>e.matches('.banner-group.book-last-dead-end__banner-group')):[],
      author:inner?[...inner.children].filter(e=>e.matches('.recommend-grid.book-last-dead-end__section.book-last-dead-end__author')):[],
      i2i:inner?[...inner.children].filter(e=>e.matches('.recommend-grid.book-last-dead-end__section.book-last-dead-end__i2i')):[]};
    terminal.moduleCounts={review:modules.review.length,coupon:modules.coupon.length,author:modules.author.length,i2i:modules.i2i.length};
    const viewer=layout?.closest('.comic-viewer')||null;
    const headerRoots=viewer?[...viewer.querySelectorAll(':scope > .legacy-comic-header')]:[];
    const header=headerRoots.length===1?headerRoots[0]:null;
    const bars=header?[...header.querySelectorAll(':scope > .legacy-comic-header__bar')]:[];
    const menus=bars.length===1?[...bars[0].querySelectorAll(':scope > .legacy-comic-header__menu--pc')]:[];
    const nativeHeaderButtons=viewer?[...viewer.querySelectorAll(
      '.legacy-comic-header button.close-button,.legacy-comic-header button.contents-button,.legacy-comic-header button.settings-button')]
      .filter(e=>visible(e)&&rect(e).viewport):[];
    const headerControls={
      'close-button':bars.length===1?[...bars[0].querySelectorAll(':scope > button.close-button')].filter(e=>visible(e)&&rect(e).viewport).length:0,
      'contents-button':menus.length===1?[...menus[0].querySelectorAll(':scope > button.contents-button')].filter(e=>visible(e)&&rect(e).viewport).length:0,
      'settings-button':menus.length===1?[...menus[0].querySelectorAll(':scope > button.settings-button')].filter(e=>visible(e)&&rect(e).viewport).length:0,
    };
    const lotteryCandidates=inner?[...inner.querySelectorAll('button.banner__row--lottery')].filter(e=>visible(e)&&rect(e).viewport):[];
    const lotteryButtons=modules.coupon.length===1?[...modules.coupon[0].querySelectorAll(':scope > button.banner__row.banner__row--lottery')]
      .filter(e=>visible(e)&&rect(e).viewport):[];
    const observedControlsVariant=lotteryCandidates.length>0||nativeHeaderButtons.length>0;
    terminal.profile=observedControlsVariant?'angel-dead-end-observed-controls':'angel-dead-end';
    terminal.variant=observedControlsVariant?'lottery-plus-native-header-v1':'line-coupon-only-v1';
    terminal.headerRootCount=headerRoots.length;terminal.headerBarCount=bars.length;terminal.headerMenuCount=menus.length;
    terminal.headerCounts=headerControls;terminal.lotteryButtonCount=lotteryButtons.length;
    terminal.markerCount=angelMarkers.length;
    const marker=angelMarkers.length===1?angelMarkers[0]:null,markerRect=marker?rect(marker):null;
    terminal.markerInsideInner=!!marker&&!!inner&&marker.parentElement===inner;
    terminal.markerVisible=!!marker&&visible(marker)&&markerRect.viewport;
    terminal.markerTextExact=!!marker&&marker.tagName==='DIV'&&normalize(marker.innerText||marker.textContent)==='\u3053\u306e\u4f5c\u54c1\u306f\u3053\u3053\u307e\u3067\u3067\u3059';
    terminal.markerControls=marker?[...marker.querySelectorAll('a,button,[role="button"],input,select,textarea,[contenteditable="true"]')].filter(visible).length:null;
    const safeModules=modules.review.length===1&&modules.coupon.length===1&&modules.author.length===1&&modules.i2i.length===1;
    if(!actionInventoryCapped&&inner&&root&&safeModules&&marker&&terminal.markerInsideInner&&terminal.markerVisible&&terminal.markerTextExact&&terminal.markerControls===0){
      for(const action of actionable){
        let category=null;
        if(!inner.contains(action)){
          const closeAction=action.matches('button.close-button')&&header&&headerRoots.includes(header)
            &&header.parentElement===viewer&&bars.length===1&&action.parentElement===bars[0];
          const contentsAction=action.matches('button.contents-button')&&header&&header.parentElement===viewer
            &&bars.length===1&&menus.length===1&&action.parentElement===menus[0];
          const settingsAction=action.matches('button.settings-button')&&header&&header.parentElement===viewer
            &&bars.length===1&&menus.length===1&&action.parentElement===menus[0];
          if(observedControlsVariant&&(closeAction||contentsAction||settingsAction))category='header';
          else terminal.unknownActionCount++;
          if(category)terminal.partition[category]=(terminal.partition[category]||0)+1;
          continue;
        }
        const review=action.closest('.review-module.book-last-dead-end__review');
        const coupon=action.closest('.banner-group.book-last-dead-end__banner-group');
        const recommendation=action.closest('.recommend-grid.book-last-dead-end__section');
        if(action.matches('button.review-module__action')&&action.parentElement===review&&modules.review.includes(review)&&review.parentElement===inner)category='review';
        else if(action.matches('button.banner__row--line-coupon')&&action.parentElement===coupon&&modules.coupon.includes(coupon)&&coupon.parentElement===inner)category='coupon';
        else if(action.matches('button.banner__row.banner__row--lottery')
          &&action.parentElement===coupon&&modules.coupon.includes(coupon)&&coupon.parentElement===inner)category='lottery';
        const directHeading=action.matches('a.recommend-grid__heading.recommend-grid__heading--more')&&action.parentElement===recommendation;
        const itemLink=action.matches('a.recommend-grid__link')&&action.parentElement?.matches('.recommend-grid__item')
          &&action.parentElement.parentElement?.matches('.recommend-grid__list')
          &&action.parentElement.parentElement.parentElement===recommendation;
        if(!category&&(directHeading||itemLink)&&recommendation?.parentElement===inner){
          if(modules.author.includes(recommendation))category='recommendAuthor';
          else if(modules.i2i.includes(recommendation))category='recommendI2i';
        }
        if(!category){terminal.unknownActionCount++;continue;}
        terminal.partition[category]=(terminal.partition[category]||0)+1;
      }
    }
    terminal.actionPartitionComplete=!actionInventoryCapped&&terminal.unknownActionCount===0&&terminal.riskyActionCount===0
      &&Object.values(terminal.partition).reduce((sum,count)=>sum+count,0)===visibleActions;
    const observedControlsValid=observedControlsVariant
      &&lotteryCandidates.length===1&&lotteryButtons.length===1&&headerRoots.length===1&&header.parentElement===viewer
      &&bars.length===1&&menus.length===1&&Object.values(headerControls).every(count=>count===1);
    const transientPartitionKeys=['coupon','lottery','recommendAuthor','recommendI2i','review'];
    const transientPartitionValid=terminal.actionPartitionComplete
      &&Object.keys(terminal.partition).length===transientPartitionKeys.length
      &&transientPartitionKeys.every(key=>Object.hasOwn(terminal.partition,key))
      &&terminal.partition.review===1&&terminal.partition.coupon===1&&terminal.partition.lottery===1
      &&terminal.partition.recommendAuthor>=1&&terminal.partition.recommendI2i>=1
      &&terminal.visibleActionCount===1+1+1+terminal.partition.recommendAuthor+terminal.partition.recommendI2i;
    const transientHiddenHeaderLoading=observedControlsVariant
      &&terminal.profile==='angel-dead-end-observed-controls'
      &&terminal.variant==='lottery-plus-native-header-v1'
      &&terminal.rootCount===1&&terminal.innerCount===1&&terminal.shellChainValid===true
      &&terminal.insidePinnedLayout===true&&terminal.rootVisible===true&&terminal.innerVisible===true
      &&terminal.rootInViewport===true&&terminal.innerInViewport===true
      &&mudaRoots.length===0&&safeModules&&terminal.markerCount===1&&terminal.markerInsideInner===true
      &&terminal.markerVisible===true&&terminal.markerTextExact===true&&terminal.markerControls===0
      &&lotteryCandidates.length===1&&lotteryButtons.length===1&&lotteryCandidates[0]===lotteryButtons[0]
      &&headerRoots.length===1&&header.parentElement===viewer&&bars.length===1&&menus.length===1
      &&nativeHeaderButtons.length===0&&Object.values(headerControls).every(count=>count===0)
      &&transientPartitionValid&&terminal.unknownActionCount===0&&terminal.riskyActionCount===0
      &&terminal.actionInventoryCapped===false&&terminal.modalCount===0
      &&terminal.visibleSlotCount===0&&terminal.visiblePageCanvasCount===0
      &&visibleSlots.length===0&&parts.length===0&&dead.length===1&&dead[0].visible===true
      &&dead[0].textExact===true&&dead[0].controls===0
      &&titleVisible===false&&counterVisible===false;
    if(transientHiddenHeaderLoading){
      return {status:'loading',routeStable:true,slotCount:slots.length,visibleSlots,parts:[],deadEnd:dead,
        visibleActions,counter:null,counterVisible:false,toolbarVisible:false,terminal};
    }
    const legacyControlsValid=!observedControlsVariant&&lotteryCandidates.length===0;
    if(terminal.insidePinnedLayout&&terminal.shellChainValid&&mudaRoots.length===0&&terminal.rootVisible&&terminal.innerVisible&&terminal.rootInViewport&&terminal.innerInViewport&&terminal.actionPartitionComplete&&modalCount===0
      &&(observedControlsValid||legacyControlsValid)){
      return {status:'end',routeStable:true,slotCount:slots.length,visibleSlots,parts:[],deadEnd:dead,visibleActions,counter,counterVisible,toolbarVisible:headerVisible||counterVisible,terminal};
    }
    return {status:'unknown-terminal-marker',routeStable:true,slotCount:slots.length,visibleSlots,parts:[],deadEnd:dead,visibleActions,toolbarVisible:headerVisible||counterVisible,terminal};
  }
  if(parts.length===0&&visibleSlots.length===0&&pageCanvasCount===0&&activeMudaRoot){
    terminal.profile='muda-book-last';terminal.rootCount=mudaRoots.length;
    const root=mudaRoots.length===1?mudaRoots[0]:null;
    const inners=root?[...root.querySelectorAll(':scope > .book-last__inner')]:[];
    terminal.innerCount=inners.length;const inner=inners.length===1?inners[0]:null;
    terminal.rootVisible=!!root&&visible(root);terminal.innerVisible=!!inner&&visible(inner);
    terminal.rootInViewport=!!root&&rect(root).viewport;terminal.innerInViewport=!!inner&&rect(inner).viewport;
    const shell=root?.parentElement?.matches('.viewer-last-shell')?root.parentElement:null;
    const lastCell=shell?.parentElement?.matches('.viewer-liber__viewer-last-cell')?shell.parentElement:null;
    const customCell=lastCell?.parentElement?.matches('.comic-viewer__custom-cell--interactive')?lastCell.parentElement:null;
    const viewer=layout?.closest('.comic-viewer')||null;
    const header=viewer?[...viewer.querySelectorAll(':scope > .legacy-comic-header')]:[];
    terminal.shellChainValid=!!root&&!!inner&&!!shell&&!!lastCell&&!!customCell&&customCell.contains(root);
    terminal.insidePinnedLayout=terminal.shellChainValid&&isUnder(customCell,layout)&&!!viewer&&header.length===1;
    const requiredModules={review:'.book-last__review',nextItem:'.book-last__next',cta:'.book-last__cta',banner:'.book-last__banner-group',i2i:'.book-last__i2i',author:'.book-last__author',forYou:'.book-last__for-you'};
    for(const [name,selector] of Object.entries(requiredModules)){
      terminal.moduleCounts[name]=inner?[...inner.children].filter(e=>e.matches(selector)).length:0;
    }
    terminal.moduleChildCount=inner?.children.length??0;
    const bars=header.length===1?[...header[0].querySelectorAll(':scope > .legacy-comic-header__bar')]:[];
    const menus=bars.length===1?[...bars[0].querySelectorAll(':scope > .legacy-comic-header__menu--pc')]:[];
    terminal.headerBarCount=bars.length;terminal.headerMenuCount=menus.length;
    const headerControls={
      'close-button':bars.length===1?[...bars[0].querySelectorAll(':scope > button.close-button')].filter(e=>visible(e)&&rect(e).viewport).length:0,
      'contents-button':menus.length===1?[...menus[0].querySelectorAll(':scope > button.contents-button')].filter(e=>visible(e)&&rect(e).viewport).length:0,
      'settings-button':menus.length===1?[...menus[0].querySelectorAll(':scope > button.settings-button')].filter(e=>visible(e)&&rect(e).viewport).length:0,
    };
    terminal.headerCounts=headerControls;
    const requiredModulesPresent=Object.values(terminal.moduleCounts).every(count=>count===1)&&Object.values(terminal.moduleCounts).length===7;
    const headerCountsValid=Object.values(headerControls).every(count=>count===1)&&bars.length===1&&menus.length===1;
    if(!actionInventoryCapped&&root&&inner&&shell&&lastCell&&customCell&&viewer&&header.length===1&&requiredModulesPresent&&headerCountsValid){
      for(const action of actionable){
        let category=null;
        const module=action.closest(Object.values(requiredModules).join(','));
        if(module&&inner.contains(module)){
          const moduleName=Object.entries(requiredModules).find(([,selector])=>module.matches(selector))?.[0]||null;
          if(moduleName==='review'&&module.parentElement===inner&&action.matches('button.review-module__action')&&action.parentElement===module)category='review';
          else if(moduleName==='nextItem'&&action.matches('button.next-item__rating')
            &&module.parentElement===inner&&action.parentElement?.matches('.next-item__outline')
            &&action.parentElement.parentElement===module)category='nextItem';
          else if(moduleName==='cta'&&action.matches('button.cta-button__read-btn')
            &&module.parentElement===inner
            &&action.parentElement?.matches('.cta-button__primary')
            &&action.parentElement.parentElement?.matches('.cta-button__row')
            &&action.parentElement.parentElement.parentElement===module)category='cta';
          else if(moduleName==='banner'&&(action.matches('button.banner__row--lottery')||action.matches('button.banner__row--line-coupon'))
            &&module.parentElement===inner
            &&action.closest('.banner-group.book-last__banner-group')===module)category='banner';
          else if(['i2i','author','forYou'].includes(moduleName)&&module.parentElement===inner
            &&action.matches('a.recommend-grid__link')&&action.parentElement?.matches('.recommend-grid__item')
            &&action.parentElement.parentElement?.matches('.recommend-grid__list')
            &&action.parentElement.parentElement.parentElement===module)category=moduleName;
          else if(moduleName==='author'&&module.parentElement===inner
            &&action.matches('a.recommend-grid__heading.recommend-grid__heading--more')&&action.parentElement===module)category='author';
        }
        const closeAction=action.matches('button.close-button')&&bars.length===1&&action.parentElement===bars[0];
        const contentsAction=action.matches('button.contents-button')&&menus.length===1&&action.parentElement===menus[0];
        const settingsAction=action.matches('button.settings-button')&&menus.length===1&&action.parentElement===menus[0];
        if(!category&&header[0].contains(action)&&(closeAction||contentsAction||settingsAction))category='header';
        if(!category){terminal.unknownActionCount++;continue;}
        terminal.partition[category]=(terminal.partition[category]||0)+1;
      }
    }
    terminal.actionPartitionComplete=!actionInventoryCapped&&terminal.unknownActionCount===0
      &&Object.values(terminal.partition).reduce((sum,count)=>sum+count,0)===visibleActions;
    if(terminal.insidePinnedLayout&&terminal.shellChainValid&&angelRoots.length===0&&angelMarkers.length===0&&terminal.rootVisible&&terminal.innerVisible&&terminal.rootInViewport&&terminal.innerInViewport&&requiredModulesPresent&&headerCountsValid&&terminal.actionPartitionComplete&&modalCount===0){
      return {status:'end',routeStable:true,slotCount:slots.length,visibleSlots,parts:[],deadEnd:dead,visibleActions,counter,counterVisible,toolbarVisible:headerVisible||counterVisible,terminal};
    }
    return {status:'unknown-terminal-marker',routeStable:true,slotCount:slots.length,visibleSlots,parts:[],deadEnd:dead,visibleActions,toolbarVisible:headerVisible||counterVisible,terminal};
  }
  if(parts.length===0&&dead.some(item=>item.visible&&item.rect.viewport))return {status:'unknown-terminal-marker',routeStable:true,slotCount:slots.length,visibleSlots,parts:[],deadEnd:dead,visibleActions,toolbarVisible:headerVisible||counterVisible};
  const current=counter?.current??expectedCurrent;
  if(parts.length===0)return {status:visibleSlots.length===0?'loading':'partial',routeStable:true,slotCount:slots.length,visibleSlots,parts:[],deadEnd:dead,visibleActions,toolbarVisible:headerVisible||counterVisible};
  const expectedParts=current===1?1:2;
  if(incomplete||parts.length!==expectedParts)return {status:'partial',routeStable:true,slotCount:slots.length,visibleSlots,parts,deadEnd:dead,toolbarVisible:headerVisible||counterVisible,current};
  return {status:'content',routeStable:true,slotCount:slots.length,visibleSlots,parts,deadEnd:dead,toolbarVisible:headerVisible||counterVisible,
    counter,title,counterVisible:!!counter&&counterVisible,viewport:{width:innerWidth,height:innerHeight}};
}"""
