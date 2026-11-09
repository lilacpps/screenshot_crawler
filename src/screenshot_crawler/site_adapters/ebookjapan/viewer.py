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
_CARD_VOLUME_SUFFIX = re.compile(r"^(?P<base>.+?)(?P<number>[1-9][0-9]{0,2})巻$")
_READER_VOLUME_SUFFIX = re.compile(r"^(?P<base>.+)\((?P<number>[1-9][0-9]{0,2})\)$")


def normalize_title(value: str) -> str:
    return "".join(unicodedata.normalize("NFKC", value).split())


def reader_title_matches_owned_title(owned_title: str, reader_title: str) -> bool:
    """Match the exact owned title or the one observed Reader title alias.

    The only non-exact alias observed is ``base N巻`` on the owned listing to
    ``base(N)`` in the Reader. Parsing is deliberately suffix-only and rejects
    ambiguous numeric bases, leading zeroes, and numbers outside 1..999.
    """

    owned = normalize_title(owned_title)
    reader = normalize_title(reader_title)
    if not owned or not reader:
        return False
    if owned == reader:
        return True
    card_match = _CARD_VOLUME_SUFFIX.fullmatch(owned)
    reader_match = _READER_VOLUME_SUFFIX.fullmatch(reader)
    if card_match is None or reader_match is None:
        return False
    card_base, reader_base = card_match.group("base"), reader_match.group("base")
    card_number, reader_number = card_match.group("number"), reader_match.group("number")
    if card_base[-1:].isdigit() or reader_base[-1:].isdigit():
        return False
    return card_base == reader_base and card_number == reader_number


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
  const sourceContextMethods=Object.getOwnPropertyNames(contextProto).filter(name=>{
    const descriptor=Object.getOwnPropertyDescriptor(contextProto,name);
    return name!=='constructor'&&!names.includes(name)&&typeof descriptor?.value==='function';
  });
  const sourceStateProperties=['globalAlpha','globalCompositeOperation','filter','shadowColor','shadowBlur','shadowOffsetX',
    'shadowOffsetY','imageSmoothingEnabled','imageSmoothingQuality'];
  const diagnosticMethodNames=['arc','beginPath','closePath','fill','stroke','clip','drawImage','getImageData','putImageData',
    'clearRect','fillRect','strokeRect','fillText','strokeText','getTransform','reset','save','restore','translate','rotate',
    'scale','transform','setTransform','resetTransform','setLineDash','isPointInPath','isPointInStroke','createImageData',
    'getContext','transferToImageBitmap','getContextAttributes','isContextLost','getLineDash','measureText','arcTo','ellipse',
    'rect','roundRect','moveTo','lineTo','quadraticCurveTo','bezierCurveTo','createPattern','createLinearGradient',
    'createRadialGradient','createConicGradient','drawFocusIfNeeded','scrollPathIntoView'];
  const diagnosticMethodSet=new Set(diagnosticMethodNames),diagnosticStateSet=new Set(sourceStateProperties);
  const sourceMethodMissing=new Set(),sourceMethodNonNative=new Set(),offscreenMethodMissing=new Set(),offscreenMethodNonNative=new Set();
  const stateSetterMissing=new Set(),stateSetterNonNative=new Set(),offscreenStateSetterMissing=new Set(),offscreenStateSetterNonNative=new Set();
  const slotMismatchMethods=new Set(),slotMismatchStateProperties=new Set();
  let diagnosticOtherMethodCount=0;
  let offscreenInstallOtherCount=0;
  const MAX_DIAGNOSTIC_OTHER=1024,MAX_UNKNOWN_SLOT_DETAILS=8,MAX_TRACKED_UNKNOWN_SLOTS=1024;
  const unknownSlotMaps=new WeakMap(),unknownMethodSlotDescriptors=[];
  let unknownMethodSlotCount=0,unknownMethodSlotDescriptorsOmittedCount=0,unknownMethodSlotOverflowCount=0;
  const recordUnknownMethodSlot=(proto,name,ownerDepth,descriptor,stage)=>{
    let slots=unknownSlotMaps.get(proto);
    if(!slots){slots=new Map();unknownSlotMaps.set(proto,slots);}
    let slot=slots.get(name);
    if(!slot){
      if(unknownMethodSlotCount>=MAX_TRACKED_UNKNOWN_SLOTS){
        unknownMethodSlotOverflowCount=Math.min(MAX_DIAGNOSTIC_OTHER,unknownMethodSlotOverflowCount+1);return;
      }
      unknownMethodSlotCount++;
      slot={opaqueId:`slot-${unknownMethodSlotCount}`,ownerDepth,offscreenInstallObserved:false,currentSlotMismatchObserved:false};
      slots.set(name,slot);
      if(unknownMethodSlotDescriptors.length<MAX_UNKNOWN_SLOT_DETAILS)unknownMethodSlotDescriptors.push(slot);
      else unknownMethodSlotDescriptorsOmittedCount++;
    }
    if(stage==='offscreen-install')slot.offscreenInstallObserved=true;
    else if(stage==='current-slot-mismatch')slot.currentSlotMismatchObserved=true;
    const dataDescriptor=!!descriptor&&Object.prototype.hasOwnProperty.call(descriptor,'value');
    slot.descriptorKind=!descriptor?'missing':dataDescriptor?'data':'accessor';
    slot.valueType=!descriptor?'missing':dataDescriptor?typeof descriptor.value:'accessor';
    slot.functionNative=dataDescriptor&&typeof descriptor.value==='function'&&native(descriptor.value);
    slot.writable=descriptor?.writable===true;
    slot.configurable=descriptor?.configurable===true;
    slot.enumerable=descriptor?.enumerable===true;
    slot.getterPresent=typeof descriptor?.get==='function';
    slot.getterNative=slot.getterPresent&&native(descriptor.get);
    slot.setterPresent=typeof descriptor?.set==='function';
    slot.setterNative=slot.setterPresent&&native(descriptor.set);
  };
  const recordDiagnosticName=(set,name,allowlist)=>{
    if(allowlist.has(name))set.add(name);
    else if(diagnosticOtherMethodCount<MAX_DIAGNOSTIC_OTHER){
      diagnosticOtherMethodCount++;
      if(set===offscreenMethodMissing||set===offscreenMethodNonNative)offscreenInstallOtherCount++;
    }
  };
  const contexts={'getContext':canvasProto,'drawImage':contextProto,'putImageData':contextProto,'clearRect':contextProto,
    'fillRect':contextProto,'strokeRect':contextProto,'fillText':contextProto,'strokeText':contextProto,'fill':contextProto,'stroke':contextProto,'clip':contextProto};
  const descriptors=Object.fromEntries(names.map(name=>[name,Object.getOwnPropertyDescriptor(contexts[name]||contextProto,name)]));
  descriptors.getTransform=Object.getOwnPropertyDescriptor(contextProto,'getTransform');
  const originals=Object.fromEntries([...names,'getTransform'].map(name=>[name,descriptors[name]?.value]));
  const native=fn=>{try{return typeof fn==='function'&&/\[native code\]/.test(Function.prototype.toString.call(fn));}catch{return false;}};
  const unavailable=[...names,'getTransform'].filter(name=>!descriptors[name]||typeof originals[name]!=='function'||!(descriptors[name].writable||descriptors[name].configurable)||!native(originals[name]));
  if(unavailable.length)return status({installed:false,reason:'native-descriptor-conflict',unavailable});
  const sourceMethodDescriptors=Object.fromEntries(sourceContextMethods.map(name=>[name,Object.getOwnPropertyDescriptor(contextProto,name)]));
  let sourceMethodCoverage=true;
  for(const name of sourceContextMethods){
    const descriptor=sourceMethodDescriptors[name];
    if(!descriptor||typeof descriptor.value!=='function'){
      sourceMethodCoverage=false;recordDiagnosticName(sourceMethodMissing,name,diagnosticMethodSet);
    }else if(!(descriptor.writable||descriptor.configurable)||!native(descriptor.value)){
      sourceMethodCoverage=false;recordDiagnosticName(sourceMethodNonNative,name,diagnosticMethodSet);
    }
  }
  for(const name of sourceContextMethods)if(typeof sourceMethodDescriptors[name]?.value==='function')originals[name]=sourceMethodDescriptors[name].value;
  const sourceStateDescriptors=Object.fromEntries(sourceStateProperties.map(name=>[name,Object.getOwnPropertyDescriptor(contextProto,name)]));
  let sourceStateCoverage=true;
  for(const name of sourceStateProperties){
    const descriptor=sourceStateDescriptors[name];
    if(!descriptor||typeof descriptor.set!=='function'){
      sourceStateCoverage=false;recordDiagnosticName(stateSetterMissing,name,diagnosticStateSet);
    }else if(!descriptor.configurable||!native(descriptor.set)){
      sourceStateCoverage=false;recordDiagnosticName(stateSetterNonNative,name,diagnosticStateSet);
    }
  }
  const routeAllowed=()=>window.top===window&&location.hostname==='ebookjapan.yahoo.co.jp'&&/^\/viewer\/purchased\/B[0-9]+\/$/.test(location.pathname)&&!location.search&&!location.hash;
  const states=new WeakMap(),contextRefs=new WeakMap(),sourceContexts=new WeakSet(),instrumentedSourcePrototypes=new WeakSet();
  const dynamicMethodWrappers=[],dynamicStateWrappers=[];
  const observedCanvases=new WeakSet();
  const MAX_DRAW_CALLS=20000;
  let calls=0,overflow=false,metadataFailures=0;
  let offscreenContextCoverage=false,sourceContextCoverageBase=false;
  let mutationObserver=null;
  const invalidateTarget=(canvas,reason)=>{try{window.__ejSourceObserver?.invalidateTarget?.(canvas,reason);}catch{metadataFailures++;window.__ejSourceObserver?.recordInstrumentationFailure?.();}};
  const markCanvasReset=(canvas,reason)=>{const state=stateFor(canvas);state.drawGeneration=0;state.mutationCount=0;
    state.lastFullDraw=false;state.lastDraw=null;state.resetObserved=true;invalidateTarget(canvas,reason);};
  const stateFor=canvas=>{let state=states.get(canvas);if(!state){state={drawGeneration:0,successfulDraws:0,mutationCount:0,clipCalls:0,lastFullDraw:false,lastDraw:null,resetObserved:false,contextIs2d:false};states.set(canvas,state);}
    if(mutationObserver&&!observedCanvases.has(canvas)){observedCanvases.add(canvas);try{mutationObserver.observe(canvas,{attributes:true,attributeFilter:['width','height']});}catch{metadataFailures++;}}
    return state;};
  const drainMutations=()=>{try{for(const record of mutationObserver.takeRecords()){if(record.target instanceof HTMLCanvasElement)markCanvasReset(record.target,'html-canvas-attribute-reset');}}catch{metadataFailures+=1;}};
  mutationObserver=new MutationObserver(records=>{for(const record of records){if(record.target instanceof HTMLCanvasElement)markCanvasReset(record.target,'html-canvas-attribute-reset');}});
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
  const wrap=(name,fn,{core=true,offscreenGetContext=false,sourceOnly=false}={})=>function(...args){
    const offscreen=typeof OffscreenCanvas!=='undefined'&&this instanceof OffscreenCanvas;
    const sourceContext=sourceContexts.has(this);
    const active=routeAllowed()&&(name==='getContext'?(offscreenGetContext?offscreen:this instanceof HTMLCanvasElement)
      :(sourceOnly?sourceContext:(this instanceof CanvasRenderingContext2D||sourceContext)));
    if(!active)return Reflect.apply(fn,this,args);
    const canvas=(this instanceof CanvasRenderingContext2D||sourceContext)?this.canvas:null;
    if(name==='drawImage'&&canvas instanceof HTMLCanvasElement)drainMutations();
    let result,didThrow=false,thrown;try{result=Reflect.apply(fn,this,args);}catch(error){didThrow=true;thrown=error;}
    if(core&&!sourceContext&&!offscreenGetContext){
      try{if(calls<MAX_DRAW_CALLS){calls++;if(name==='getContext'&&!offscreenGetContext){const state=stateFor(this);state.contextIs2d=!didThrow&&String(args[0]).toLowerCase()==='2d'&&result instanceof CanvasRenderingContext2D;if(state.contextIs2d)contextRefs.set(this,result);}
        else if(canvas instanceof HTMLCanvasElement){const state=stateFor(canvas);if(name==='clip'){state.clipCalls++;invalidateTarget(canvas,'html-context-clip');}
          else if(name==='drawImage'){if(!didThrow){state.drawGeneration++;state.successfulDraws++;state.mutationCount++;state.resetObserved=false;const geometry=fullGeometry(this,args);state.lastFullDraw=geometry.eligible&&state.clipCalls===0;state.lastDraw=geometry;}}
          else if(name==='reset'&&!didThrow){state.drawGeneration=0;state.mutationCount=0;state.clipCalls=0;state.lastFullDraw=false;state.lastDraw=null;state.resetObserved=true;invalidateTarget(canvas,'html-context-reset');}
          else if(!didThrow){state.mutationCount++;state.lastFullDraw=false;state.lastDraw={method:name,targetWidth:canvas.width,targetHeight:canvas.height};invalidateTarget(canvas,'html-context-mutation');}}
      }else overflow=true;}catch{metadataFailures++;}
    }
    try{
      const source=window.__ejSourceObserver;
      if(source&&routeAllowed()){
        if(name==='getContext'&&offscreenGetContext){
          const exactNativeContext=!didThrow&&result&&result.canvas===this;
          if(exactNativeContext)sourceContexts.add(result);
          offscreenContextCoverage=!!exactNativeContext&&instrumentSourceContext(result);
          source.setContextWrapperCoverage?.(sourceContextCoverageBase&&offscreenContextCoverage);
          source.recordContextReturn?.(this,args,didThrow,result);
        }
        else if(canvas instanceof OffscreenCanvas)source.recordSourceContextCall?.(name,this,args,didThrow);
        else if(canvas instanceof HTMLCanvasElement&&name==='drawImage')source.recordTargetDraw?.(this,args,didThrow,states.get(canvas)||null);
      }
    }catch{metadataFailures++;try{window.__ejSourceObserver?.recordInstrumentationFailure?.();}catch{}}
    if(didThrow)throw thrown;return result;
  };
  const wrappers={};for(const name of names){wrappers[name]=wrap(name,originals[name]);Object.defineProperty(contexts[name]||contextProto,name,{...descriptors[name],value:wrappers[name]});}
  const sourceMethodWrappers={};
  for(const name of sourceContextMethods){
    const descriptor=sourceMethodDescriptors[name];
    if(!descriptor||typeof descriptor.value!=='function'||!(descriptor.writable||descriptor.configurable)||!native(descriptor.value)){sourceMethodCoverage=false;continue;}
    sourceMethodWrappers[name]=wrap(name,descriptor.value,{core:false,sourceOnly:true});
    Object.defineProperty(contextProto,name,{...descriptor,value:sourceMethodWrappers[name]});
  }
  const sourceStateWrappers={};
  for(const name of sourceStateProperties){
    const descriptor=sourceStateDescriptors[name];
    if(!descriptor?.set||!descriptor.configurable||!native(descriptor.set)){sourceStateCoverage=false;continue;}
    sourceStateWrappers[name]=function(value){
      let result,didThrow=false,thrown;try{result=Reflect.apply(descriptor.set,this,[value]);}catch(error){didThrow=true;thrown=error;}
      try{if(!didThrow&&(this instanceof CanvasRenderingContext2D||sourceContexts.has(this))){const canvas=this.canvas;
        if(canvas instanceof OffscreenCanvas)window.__ejSourceObserver?.recordStateMutation?.(this,name,false);
        else if(canvas instanceof HTMLCanvasElement)invalidateTarget(canvas,'html-context-state-mutation');}}
      catch{metadataFailures++;try{window.__ejSourceObserver?.recordInstrumentationFailure?.();}catch{}}
      if(didThrow)throw thrown;return result;
    };
    Object.defineProperty(contextProto,name,{...descriptor,set:sourceStateWrappers[name]});
  }
  const instrumentSourceContext=context=>{
    const first=Object.getPrototypeOf(context);if(!first)return false;
    if(instrumentedSourcePrototypes.has(first))return offscreenContextCoverage;
    instrumentedSourcePrototypes.add(first);
    let complete=sourceMethodCoverage&&sourceStateCoverage;
    for(let proto=first,ownerDepth=0;proto&&proto!==Object.prototype;proto=Object.getPrototypeOf(proto),ownerDepth++){
      if(proto===contextProto)break;
      for(const name of Object.getOwnPropertyNames(proto)){
        if(name==='constructor')continue;
        const descriptor=Object.getOwnPropertyDescriptor(proto,name);
        if(typeof descriptor?.value!=='function'){
          if(diagnosticMethodSet.has(name)){complete=false;offscreenMethodMissing.add(name);}
          continue;
        }
        if(descriptor.value===wrappers[name]||descriptor.value===sourceMethodWrappers[name])continue;
        if(!(descriptor.writable||descriptor.configurable)||!native(descriptor.value)){
          complete=false;recordDiagnosticName(offscreenMethodNonNative,name,diagnosticMethodSet);
          if(!diagnosticMethodSet.has(name))recordUnknownMethodSlot(proto,name,ownerDepth,descriptor,'offscreen-install');
          continue;}
        const wrapper=wrap(name,descriptor.value,{core:false,sourceOnly:true});
        Object.defineProperty(proto,name,{...descriptor,value:wrapper});
        dynamicMethodWrappers.push({proto,name,descriptor,wrapper,ownerDepth});
      }
      for(const name of sourceStateProperties){
        const descriptor=Object.getOwnPropertyDescriptor(proto,name);
        if(!descriptor)continue;
        if(!descriptor.set){complete=false;offscreenStateSetterMissing.add(name);continue;}
        if(descriptor.set===sourceStateWrappers[name])continue;
        if(!descriptor.configurable||!native(descriptor.set)){
          complete=false;recordDiagnosticName(offscreenStateSetterNonNative,name,diagnosticStateSet);continue;}
        const wrapper=function(value){
          let result,didThrow=false,thrown;try{result=Reflect.apply(descriptor.set,this,[value]);}catch(error){didThrow=true;thrown=error;}
          try{if(!didThrow&&sourceContexts.has(this))window.__ejSourceObserver?.recordStateMutation?.(this,name,false);}
          catch{metadataFailures++;try{window.__ejSourceObserver?.recordInstrumentationFailure?.();}catch{}}
          if(didThrow)throw thrown;return result;
        };
        Object.defineProperty(proto,name,{...descriptor,set:wrapper});
        dynamicStateWrappers.push({proto,name,descriptor,wrapper});
      }
    }
    offscreenContextCoverage=complete;
    return complete;
  };
  const offscreenGetContextDescriptor=typeof OffscreenCanvas!=='undefined'?Object.getOwnPropertyDescriptor(OffscreenCanvas.prototype,'getContext'):null;
  let offscreenGetContextWrapper=null,offscreenGetContextCoverage=!!offscreenGetContextDescriptor
    &&typeof offscreenGetContextDescriptor.value==='function'&&(offscreenGetContextDescriptor.writable||offscreenGetContextDescriptor.configurable)
    &&native(offscreenGetContextDescriptor.value);
  if(!offscreenGetContextDescriptor||typeof offscreenGetContextDescriptor.value!=='function')
    recordDiagnosticName(sourceMethodMissing,'getContext',diagnosticMethodSet);
  else if(!(offscreenGetContextDescriptor.writable||offscreenGetContextDescriptor.configurable)||!native(offscreenGetContextDescriptor.value))
    recordDiagnosticName(sourceMethodNonNative,'getContext',diagnosticMethodSet);
  if(offscreenGetContextCoverage){offscreenGetContextWrapper=wrap('getContext',offscreenGetContextDescriptor.value,{core:false,offscreenGetContext:true});
    Object.defineProperty(OffscreenCanvas.prototype,'getContext',{...offscreenGetContextDescriptor,value:offscreenGetContextWrapper});}
  const htmlDimensionDescriptors=Object.fromEntries(['width','height'].map(name=>[name,Object.getOwnPropertyDescriptor(canvasProto,name)]));
  const htmlDimensionWrappers={};
  let htmlDimensionCoverage=true;
  for(const name of ['width','height']){
    const descriptor=htmlDimensionDescriptors[name];
    if(!descriptor?.set||!descriptor.configurable||!native(descriptor.set)){htmlDimensionCoverage=false;continue;}
    htmlDimensionWrappers[name]=function(value){
      let result,didThrow=false,thrown;try{result=Reflect.apply(descriptor.set,this,[value]);}catch(error){didThrow=true;thrown=error;}
      if(!didThrow&&routeAllowed()&&this instanceof HTMLCanvasElement)markCanvasReset(this,'html-canvas-dimension-reset');
      if(didThrow)throw thrown;return result;
    };
    Object.defineProperty(canvasProto,name,{...descriptor,set:htmlDimensionWrappers[name]});
  }
  sourceContextCoverageBase=sourceMethodCoverage&&sourceStateCoverage&&offscreenGetContextCoverage&&htmlDimensionCoverage;
  try{window.__ejSourceObserver?.setContextWrapperCoverage?.(false);}
  catch{metadataFailures++;try{window.__ejSourceObserver?.recordInstrumentationFailure?.();}catch{}}
  const sourceInstrumentationDiagnostic=()=>{
    const mismatchedMethods=new Set(),mismatchedState=new Set(),mismatchedDimensions=new Set();
    let currentSlotOtherCount=0;
    const noteMismatch=(name,set,allowlist,slot=null)=>{
      if(allowlist.has(name))set.add(name);
      else{
        currentSlotOtherCount=Math.min(MAX_DIAGNOSTIC_OTHER,currentSlotOtherCount+1);
        if(slot)recordUnknownMethodSlot(slot.proto,name,slot.ownerDepth,slot.descriptor,'current-slot-mismatch');
      }
    };
    for(const name of names)if((contexts[name]||contextProto)[name]!==wrappers[name])
      noteMismatch(name,mismatchedMethods,diagnosticMethodSet);
    for(const name of sourceContextMethods){
      if(sourceMethodWrappers[name]&&Object.getOwnPropertyDescriptor(contextProto,name)?.value!==sourceMethodWrappers[name])
        noteMismatch(name,mismatchedMethods,diagnosticMethodSet);
    }
    for(const name of sourceStateProperties){
      if(sourceStateWrappers[name]&&Object.getOwnPropertyDescriptor(contextProto,name)?.set!==sourceStateWrappers[name])
        noteMismatch(name,mismatchedState,diagnosticStateSet);
    }
    for(const entry of dynamicMethodWrappers){
      const currentDescriptor=Object.getOwnPropertyDescriptor(entry.proto,entry.name);
      if(currentDescriptor?.value!==entry.wrapper)
        noteMismatch(entry.name,mismatchedMethods,diagnosticMethodSet,
          {proto:entry.proto,ownerDepth:entry.ownerDepth,descriptor:currentDescriptor});
    }
    for(const entry of dynamicStateWrappers){
      if(Object.getOwnPropertyDescriptor(entry.proto,entry.name)?.set!==entry.wrapper)
        noteMismatch(entry.name,mismatchedState,diagnosticStateSet);
    }
    if(offscreenGetContextWrapper&&OffscreenCanvas.prototype.getContext!==offscreenGetContextWrapper)
      noteMismatch('getContext',mismatchedMethods,diagnosticMethodSet);
    for(const name of ['width','height']){
      if(htmlDimensionWrappers[name]&&Object.getOwnPropertyDescriptor(canvasProto,name)?.set!==htmlDimensionWrappers[name])
        mismatchedDimensions.add(name);
    }
    return {sourceMethodCoverage,sourceStateCoverage,offscreenInstall:offscreenContextCoverage,
      currentSlotMismatch:mismatchedMethods.size+mismatchedState.size+mismatchedDimensions.size+currentSlotOtherCount>0,
      sourceMethodMissing:[...sourceMethodMissing],sourceMethodNonNative:[...sourceMethodNonNative],
      offscreenMethodMissing:[...offscreenMethodMissing],offscreenMethodNonNative:[...offscreenMethodNonNative],
      stateSetterMissing:[...stateSetterMissing],stateSetterNonNative:[...stateSetterNonNative],
      offscreenStateSetterMissing:[...offscreenStateSetterMissing],offscreenStateSetterNonNative:[...offscreenStateSetterNonNative],
      slotMismatchMethods:[...mismatchedMethods],slotMismatchStateProperties:[...mismatchedState],
      slotMismatchDimensionProperties:[...mismatchedDimensions],
      offscreenInstallOtherCount:Math.min(MAX_DIAGNOSTIC_OTHER,offscreenInstallOtherCount),
      currentSlotOtherCount,
      unknownMethodSlotCount:Math.min(MAX_DIAGNOSTIC_OTHER,unknownMethodSlotCount+unknownMethodSlotOverflowCount),
      unknownMethodSlotDescriptorsOmittedCount:Math.min(MAX_DIAGNOSTIC_OTHER,
        unknownMethodSlotDescriptorsOmittedCount+unknownMethodSlotOverflowCount),
      unknownMethodSlotOverflow:unknownMethodSlotOverflowCount>0,
      unknownMethodSlotDescriptors:unknownMethodSlotDescriptors.map(slot=>({...slot})),
      otherMethodCount:Math.min(MAX_DIAGNOSTIC_OTHER,diagnosticOtherMethodCount+currentSlotOtherCount)};
  };
  const sourceInstrumentationIsCurrent=()=>{
    const diagnostic=sourceInstrumentationDiagnostic();
    return sourceContextCoverageBase&&offscreenContextCoverage&&!diagnostic.currentSlotMismatch;
  };
  const observer={isInstalled:()=>names.every(name=>(contexts[name]||contextProto)[name]===wrappers[name]),
    health(){return {installed:names.every(name=>(contexts[name]||contextProto)[name]===wrappers[name]),overflow,metadataFailures,callCount:calls,
      sourceInstrumentationCurrent:sourceInstrumentationIsCurrent(),sourceInstrumentationDiagnostic:sourceInstrumentationDiagnostic()};},
    sourceInstrumentationIsCurrent,
    sourceInstrumentationDiagnostic,
    statusFor(canvas){drainMutations();if(!(canvas instanceof HTMLCanvasElement))return null;const state=states.get(canvas);return state?{drawGeneration:state.drawGeneration,successfulDraws:state.successfulDraws,mutationCount:state.mutationCount,clipCalls:state.clipCalls,lastFullDraw:state.lastFullDraw,lastDraw:state.lastDraw,resetObserved:state.resetObserved,contextIs2d:state.contextIs2d,canvasWidth:canvas.width,canvasHeight:canvas.height,overflow,metadataFailures}:null;},
    stop(){mutationObserver.disconnect();const restored={};for(const name of names){restored[name]=false;const proto=contexts[name]||contextProto;if(proto[name]===wrappers[name]){Object.defineProperty(proto,name,descriptors[name]);restored[name]=proto[name]===originals[name];}}
      for(const name of sourceContextMethods){restored[`source:${name}`]=false;if(sourceMethodWrappers[name]&&contextProto[name]===sourceMethodWrappers[name]){Object.defineProperty(contextProto,name,sourceMethodDescriptors[name]);restored[`source:${name}`]=contextProto[name]===sourceMethodDescriptors[name].value;}}
      for(const name of sourceStateProperties){restored[`state:${name}`]=false;const current=Object.getOwnPropertyDescriptor(contextProto,name);if(sourceStateWrappers[name]&&current?.set===sourceStateWrappers[name]){Object.defineProperty(contextProto,name,sourceStateDescriptors[name]);restored[`state:${name}`]=Object.getOwnPropertyDescriptor(contextProto,name)?.set===sourceStateDescriptors[name].set;}}
      for(const entry of dynamicMethodWrappers.reverse()){restored[`dynamic:${entry.name}`]=false;if(entry.proto[entry.name]===entry.wrapper){Object.defineProperty(entry.proto,entry.name,entry.descriptor);restored[`dynamic:${entry.name}`]=entry.proto[entry.name]===entry.descriptor.value;}}
      for(const entry of dynamicStateWrappers.reverse()){restored[`dynamic-state:${entry.name}`]=false;const current=Object.getOwnPropertyDescriptor(entry.proto,entry.name);if(current?.set===entry.wrapper){Object.defineProperty(entry.proto,entry.name,entry.descriptor);restored[`dynamic-state:${entry.name}`]=Object.getOwnPropertyDescriptor(entry.proto,entry.name)?.set===entry.descriptor.set;}}
      if(offscreenGetContextWrapper&&OffscreenCanvas.prototype.getContext===offscreenGetContextWrapper){Object.defineProperty(OffscreenCanvas.prototype,'getContext',offscreenGetContextDescriptor);restored.offscreenGetContext=OffscreenCanvas.prototype.getContext===offscreenGetContextDescriptor.value;}
      for(const name of ['width','height']){restored[`canvas:${name}`]=false;if(htmlDimensionWrappers[name]&&Object.getOwnPropertyDescriptor(canvasProto,name)?.set===htmlDimensionWrappers[name]){Object.defineProperty(canvasProto,name,htmlDimensionDescriptors[name]);restored[`canvas:${name}`]=Object.getOwnPropertyDescriptor(canvasProto,name)?.set===htmlDimensionDescriptors[name].set;}}
      status({installed:false,stopped:true,restored});return {restored,callCount:calls,overflow,metadataFailures};}};
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
  window.__ejReaderAnchor={document,pathname:location.pathname,title:normalize(expectedTitle),total:counter.total,slots,weak,ids,layout,canvasWeak:new WeakMap(),nextCanvasId:0,
    opacityCandidateFrameEpoch:0,opacityCandidateWeak:new WeakMap(),opacityCandidateRefs:new Map(),nextOpacityCandidateId:0,opacityCandidateOverflow:false};
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
  const frameEpoch=a?(()=>{
    a.opacityCandidateFrameEpoch=Number.isSafeInteger(a.opacityCandidateFrameEpoch)?a.opacityCandidateFrameEpoch+1:1;
    a.opacityCandidateWeak=new WeakMap();a.opacityCandidateRefs=new Map();a.nextOpacityCandidateId=0;a.opacityCandidateOverflow=false;
    return a.opacityCandidateFrameEpoch;
  })():0;
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
  const registerOpacityCandidate=element=>{
    if(!a||!Number.isSafeInteger(frameEpoch)||typeof WeakRef!=='function'){
      if(a)a.opacityCandidateOverflow=true;
      return null;
    }
    let candidateId=a.opacityCandidateWeak.get(element);
    if(candidateId)return candidateId;
    if(a.opacityCandidateRefs.size>=8){a.opacityCandidateOverflow=true;return null;}
    candidateId=++a.nextOpacityCandidateId;
    a.opacityCandidateWeak.set(element,candidateId);
    a.opacityCandidateRefs.set(candidateId,new WeakRef(element));
    return candidateId;
  };
  const aggregateContentIsOpacitySuppressed=container=>{
    try{
      if(!(container instanceof HTMLDivElement)||container.namespaceURI!=='http://www.w3.org/1999/xhtml'
        ||!container.isConnected||container.getRootNode()!==document||document.fullscreenElement)return false;
      let ancestorCount=0,reachedDocumentElement=false;
      for(let node=container;node;node=node.parentElement){
        ancestorCount+=1;if(ancestorCount>64)return false;
        if(!(node instanceof HTMLElement)||node.namespaceURI!=='http://www.w3.org/1999/xhtml'
          ||node.localName==='slot'||node.localName.includes('-')||node.shadowRoot
          ||node.matches('dialog,[popover],[role="dialog"],[aria-modal="true"]'))return false;
        if(node===document.documentElement){reachedDocumentElement=true;break;}
      }
      if(!reachedDocumentElement)return false;
      for(const overlay of document.querySelectorAll('dialog[open],[popover],[role="dialog"],[aria-modal="true"]')){
        if(overlay.matches('dialog[open]'))return false;
        if(overlay.hasAttribute('popover')){
          try{if(overlay.matches(':popover-open'))return false;}catch{return false;}
        }
        if(visible(overlay)&&overlay.matches('[role="dialog"],[aria-modal="true"]'))return false;
      }
      if(container.matches('img,canvas,svg,video,iframe'))return false;
      let visited=1;
      const stack=[...container.childNodes].reverse().map(node=>({node,opacitySuppressed:false}));
      while(stack.length){
        const entry=stack.pop(),node=entry.node;
        visited+=1;if(visited>512)return false;
        if(node.nodeType===3){
          if(typeof node.nodeValue!=='string')return false;
          if(node.nodeValue.trim()&&!entry.opacitySuppressed)return false;
          continue;
        }
        if(node.nodeType===8)continue;
        if(node.nodeType!==1||!(node instanceof Element)||node.namespaceURI!=='http://www.w3.org/1999/xhtml'
          &&node.namespaceURI!=='http://www.w3.org/2000/svg')return false;
        if(node.localName==='slot'||node.localName.includes('-')||node.shadowRoot
          ||node.matches('dialog,[popover],[role="dialog"],[aria-modal="true"]'))return false;
        const style=getComputedStyle(node),opacityText=style.opacity;
        if(typeof opacityText!=='string'||!opacityText.trim())return false;
        const opacity=Number(opacityText);
        if(!Number.isFinite(opacity))return false;
        const opacitySuppressed=entry.opacitySuppressed||opacity===0;
        if(!opacitySuppressed)return false;
        for(let index=node.childNodes.length-1;index>=0;index--)
          stack.push({node:node.childNodes[index],opacitySuppressed});
      }
      return true;
    }catch{return false;}
  };
  const hasPaintRisk=(element,conditionalCandidates)=>{
    const s=getComputedStyle(element);
    if(Number(s.opacity)!==1||s.filter!=='none'||s.backdropFilter!=='none'||s.mixBlendMode!=='normal'
      ||s.clipPath!=='none'||s.maskImage!=='none'||s.backgroundImage!=='none'||paintsColor(s.backgroundColor)
      ||s.boxShadow!=='none'||s.textShadow!=='none'||(s.outlineStyle!=='none'&&paintsColor(s.outlineColor)))return true;
    if((Number.parseFloat(s.borderTopWidth)>0&&paintsColor(s.borderTopColor))
      ||(Number.parseFloat(s.borderRightWidth)>0&&paintsColor(s.borderRightColor))
      ||(Number.parseFloat(s.borderBottomWidth)>0&&paintsColor(s.borderBottomColor))
      ||(Number.parseFloat(s.borderLeftWidth)>0&&paintsColor(s.borderLeftColor)))return true;
    for(const pseudo of ['::before','::after']){
      const p=getComputedStyle(element,pseudo);
      if(p.content&&p.content!=='none'&&p.content!=='normal')return true;
    }
    const aggregateTextRisk=!!(element.textContent||'').trim()&&paintsColor(s.color);
    const ownMedia=element.matches('img,canvas,svg,video,iframe');
    const descendantMedia=!!element.querySelector('img,canvas,svg,video,iframe');
    if(ownMedia)return true;
    if(!aggregateTextRisk&&!descendantMedia)return false;
    if(!aggregateContentIsOpacitySuppressed(element))return true;
    const candidateId=registerOpacityCandidate(element);
    if(candidateId===null)return true;
    conditionalCandidates.add(candidateId);
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
  if(a)a.opacityCandidateCheck=(candidateId,candidateFrameEpoch,targets,expectedCandidate)=>{
    try{
      if(!Number.isSafeInteger(candidateId)||candidateId<1||candidateId>8
        ||candidateFrameEpoch!==frameEpoch||a.opacityCandidateFrameEpoch!==frameEpoch
        ||!Array.isArray(targets)||targets.length<1||targets.length>2)return false;
      const candidate=a.opacityCandidateRefs.get(candidateId)?.deref();
      if(!candidate||candidate!==expectedCandidate||!candidate.isConnected||candidate.getRootNode()!==document)return false;
      for(const target of targets){
        if(!target||!Number.isSafeInteger(target.slotOrdinal)||target.slotOrdinal<0
          ||!Number.isSafeInteger(target.canvasIndex)||target.canvasIndex<0
          ||!Number.isSafeInteger(target.canvasId)||target.canvasId<1||!target.rect)return false;
        const slot=a.slots[target.slotOrdinal],canvas=slot?.querySelectorAll('canvas')[target.canvasIndex];
        if(!slot||!canvas||a.canvasWeak.get(canvas)!==target.canvasId)return false;
        const actual=canvas.getBoundingClientRect(),expectedRect=target.rect;
        if(['left','right','top','bottom','width','height'].some(key=>actual[key]!==expectedRect[key]))return false;
        const candidateRect=candidate.getBoundingClientRect();
        if(candidateRect.right<=actual.left||candidateRect.left>=actual.right
          ||candidateRect.bottom<=actual.top||candidateRect.top>=actual.bottom)return false;
      }
      const currentCandidates=new Set();
      return visible(candidate)&&!hasOutsetPaintRisk(candidate)
        &&!hasPaintRisk(candidate,currentCandidates)&&currentCandidates.has(candidateId);
    }catch{return false;}
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
    const conditionalCandidates=new Set();
    const r=canvas.getBoundingClientRect(),style=getComputedStyle(canvas);
    if(r.left < -0.5 || r.top < -0.5 || r.right > innerWidth+0.5 || r.bottom > innerHeight+0.5) return {reason:'outside-viewport',candidateIds:[]};
    if(hasOutsetPaintRisk(canvas))return {reason:'canvas-outset-paint',candidateIds:[]};
    if(style.transform!=='none'||style.clipPath!=='none'||style.maskImage!=='none'||Number(style.opacity)!==1
      ||style.filter!=='none'||style.mixBlendMode!=='normal'||style.backgroundImage!=='none'||paintsColor(style.backgroundColor)) return {reason:'canvas-compositing-style',candidateIds:[]};
    const ancestors=new Set();
    for(let node=canvas.parentElement;node;node=node.parentElement){
      ancestors.add(node);
      const s=getComputedStyle(node),box=node.getBoundingClientRect();
      if(hasOutsetPaintRisk(node))return {reason:'ancestor-outset-paint',candidateIds:[]};
      if(s.clipPath!=='none'||s.maskImage!=='none'||s.transform!=='none'||Number(s.opacity)!==1
        ||s.filter!=='none'||s.backdropFilter!=='none'||s.mixBlendMode!=='normal') return {reason:'ancestor-compositing-style',candidateIds:[]};
      for(const pseudo of ['::before','::after']){
        const p=getComputedStyle(node,pseudo);
        if(p.content&&p.content!=='none'&&p.content!=='normal')return {reason:'ancestor-pseudo-element',candidateIds:[]};
      }
      const clipX=['hidden','clip','scroll','auto'].includes(s.overflowX),clipY=['hidden','clip','scroll','auto'].includes(s.overflowY);
      const left=box.left+node.clientLeft,top=box.top+node.clientTop,right=left+node.clientWidth,bottom=top+node.clientHeight;
      if((clipX&&(r.left<left-0.5||r.right>right+0.5))||(clipY&&(r.top<top-0.5||r.bottom>bottom+0.5))) return {reason:'ancestor-overflow-clip',candidateIds:[]};
    }
    const all=document.querySelectorAll('*');
    if(all.length>20000)return {reason:'dom-inventory-limit',candidateIds:[]};
    for(const element of all){
      if(element===canvas||ancestors.has(element)||canvas.contains(element)||!visible(element))continue;
      if(hasOutsetPaintRisk(element)&&!finiteOutlineOnlyImageDisjointFromTarget(element,r))
        return {reason:'outset-painted-element:'+element.tagName.toLowerCase(),candidateIds:[]};
      const o=element.getBoundingClientRect();
      if(o.right<=r.left||o.left>=r.right||o.bottom<=r.top||o.top>=r.bottom)continue;
      if(hasPaintRisk(element,conditionalCandidates))return {reason:'intersecting-painted-element:'+element.tagName.toLowerCase(),candidateIds:[]};
    }
    if(a?.opacityCandidateOverflow)return {reason:'opacity-candidate-limit',candidateIds:[]};
    for(const fy of [0.1,0.3,0.5,0.7,0.9]) for(const fx of [0.1,0.3,0.5,0.7,0.9]){
      const x=r.left+r.width*fx,y=r.top+r.height*fy,top=document.elementFromPoint(x,y);
      if(top!==canvas&&!canvas.contains(top)) return {reason:'occluded-sample-point',candidateIds:[]};
    }
    return {reason:conditionalCandidates.size?'opacity-shadow-proof-required':null,candidateIds:[...conditionalCandidates]};
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
      cssRect:cr,captureSurfaceSafe:captureSurface.reason===null,captureSurfaceReason:captureSurface.reason,
      captureSurfaceCandidates:captureSurface.candidateIds.map(candidateId=>({candidateId,frameEpoch})),
      backingAspect,cssAspect,drawGeneration:draw?.drawGeneration??null,successfulDraws:draw?.successfulDraws??null,mutationCount:draw?.mutationCount??null,clipCalls:draw?.clipCalls??null,
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
    unknownOutsideKnownRegionCount:0,unknownActionScopeKnown:false,riskyActionCount:0,partition:{},moduleCounts:{},newArrivalShapeValid:false,headerCounts:{},nativeCounterVisible:counterVisible,nativeCounter:counter};
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
      i2i:inner?[...inner.children].filter(e=>e.matches('.recommend-grid.book-last-dead-end__section.book-last-dead-end__i2i')):[],
      newArrival:inner?[...inner.children].filter(e=>e.matches('.recommend-grid.book-last-dead-end__section.book-last-dead-end__new-arrival')):[]};
    terminal.moduleCounts={review:modules.review.length,coupon:modules.coupon.length,author:modules.author.length,i2i:modules.i2i.length,newArrival:modules.newArrival.length};
    const newArrivalShapeValid=modules.newArrival.length===0||(()=>{
      if(modules.newArrival.length!==1)return false;
      const module=modules.newArrival[0];
      if(module.tagName!=='SECTION')return false;
      const headings=[...module.children].filter(e=>e.matches('a.recommend-grid__heading.recommend-grid__heading--more'));
      const lists=[...module.children].filter(e=>e.matches('ul.recommend-grid__list'));
      if(module.children.length!==2||headings.length!==1||lists.length!==1)return false;
      const items=[...lists[0].children];
      if(items.length!==1||!items[0].matches('li.recommend-grid__item'))return false;
      const links=[...items[0].children].filter(e=>e.matches('a.recommend-grid__link'));
      return items[0].children.length===1&&links.length===1;
    })();
    terminal.newArrivalShapeValid=newArrivalShapeValid;
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
    const knownHeaderRegion=header&&header.parentElement===viewer?header:null;
    terminal.unknownActionScopeKnown=!!root&&!!inner&&terminal.shellChainValid&&terminal.insidePinnedLayout;
    terminal.unknownOutsideKnownRegionCount=actionable.filter(
      action=>!root?.contains(action)&&!knownHeaderRegion?.contains(action)).length;
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
    const safeModules=modules.review.length===1&&modules.coupon.length===1&&modules.author.length===1
      &&modules.i2i.length===1&&newArrivalShapeValid;
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
          else if(modules.newArrival.includes(recommendation))category='recommendNewArrival';
        }
        if(!category){terminal.unknownActionCount++;continue;}
        terminal.partition[category]=(terminal.partition[category]||0)+1;
      }
    }
    const newArrivalActionCount=terminal.partition.recommendNewArrival||0;
    const newArrivalPartitionValid=(modules.newArrival.length===0&&!Object.prototype.hasOwnProperty.call(terminal.partition,'recommendNewArrival'))
      ||(modules.newArrival.length===1&&newArrivalActionCount===2);
    terminal.actionPartitionComplete=!actionInventoryCapped&&terminal.unknownActionCount===0&&terminal.riskyActionCount===0
      &&newArrivalPartitionValid
      &&Object.values(terminal.partition).reduce((sum,count)=>sum+count,0)===visibleActions;
    const observedControlsValid=observedControlsVariant
      &&lotteryCandidates.length===1&&lotteryButtons.length===1&&headerRoots.length===1&&header.parentElement===viewer
      &&bars.length===1&&menus.length===1&&Object.values(headerControls).every(count=>count===1);
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
    const globalHeaders=[...document.querySelectorAll('.legacy-comic-header')];
    terminal.shellChainValid=!!root&&!!inner&&!!shell&&!!lastCell&&!!customCell&&customCell.contains(root);
    terminal.insidePinnedLayout=terminal.shellChainValid&&isUnder(customCell,layout);
    terminal.viewerIdentityValid=!!viewer&&document.querySelectorAll('.comic-viewer').length===1
      &&layout===a?.layout&&viewer===layout.closest('.comic-viewer');
    terminal.headerRootCount=header.length;
    terminal.headerGlobalCount=globalHeaders.length;
    const requiredModules={review:'.book-last__review',nextItem:'.book-last__next',cta:'.book-last__cta',banner:'.book-last__banner-group',i2i:'.book-last__i2i',author:'.book-last__author',forYou:'.book-last__for-you'};
    for(const [name,selector] of Object.entries(requiredModules)){
      terminal.moduleCounts[name]=inner?[...inner.children].filter(e=>e.matches(selector)).length:0;
    }
    terminal.moduleChildCount=inner?.children.length??0;
    const headerNode=header.length===1?header[0]:null;
    const bars=headerNode?[...headerNode.querySelectorAll(':scope > .legacy-comic-header__bar')]:[];
    const menus=bars.length===1?[...bars[0].querySelectorAll(':scope > .legacy-comic-header__menu--pc')]:[];
    terminal.headerBarCount=bars.length;terminal.headerMenuCount=menus.length;
    const headerControls={
      'close-button':bars.length===1?[...bars[0].querySelectorAll(':scope > button.close-button')].filter(e=>visible(e)&&rect(e).viewport).length:0,
      'contents-button':menus.length===1?[...menus[0].querySelectorAll(':scope > button.contents-button')].filter(e=>visible(e)&&rect(e).viewport).length:0,
      'settings-button':menus.length===1?[...menus[0].querySelectorAll(':scope > button.settings-button')].filter(e=>visible(e)&&rect(e).viewport).length:0,
    };
    terminal.headerCounts=headerControls;
    const requiredModulesPresent=Object.values(terminal.moduleCounts).every(count=>count===1)&&Object.values(terminal.moduleCounts).length===7;
    const headerCountsValid=Object.values(headerControls).every(count=>count===1)&&header.length===1&&bars.length===1&&menus.length===1;
    const headerShapeBounded=header.length<=1&&globalHeaders.length===header.length&&bars.length<=1&&menus.length<=1
      &&Object.values(headerControls).every(count=>count<=1);
    const matildaAnchors=inner?[...inner.querySelectorAll('a.matilda-banner')]:[];
    const matildaAnchor=matildaAnchors.length===1?matildaAnchors[0]:null;
    const baseTerminalStructure=!!root&&!!inner&&terminal.rootVisible&&terminal.innerVisible
      &&terminal.rootInViewport&&terminal.innerInViewport&&terminal.shellChainValid&&terminal.insidePinnedLayout
      &&terminal.viewerIdentityValid&&requiredModulesPresent&&terminal.moduleChildCount===7
      &&angelRoots.length===0&&angelMarkers.length===0&&pageCanvasCount===0&&visibleSlots.length===0&&modalCount===0;
    if(!actionInventoryCapped&&baseTerminalStructure&&headerShapeBounded){
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
          else if(moduleName==='banner'&&action===matildaAnchor&&matildaAnchor.tagName==='A'
            &&matildaAnchor.parentElement?.matches('div.matilda-module')
            &&matildaAnchor.parentElement.parentElement===module
            &&module.matches('div.banner-group.book-last__banner-group')&&module.parentElement===inner
            &&matildaAnchor.hasAttribute('href')&&matildaAnchor.getAttribute('target')==='_blank')category='matildaBanner';
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
        if(!category&&headerNode?.contains(action)&&(closeAction||contentsAction||settingsAction))category='header';
        if(!category){
          terminal.unknownActionCount++;
          if(!inner.contains(action)&&!headerNode?.contains(action))terminal.unknownOutsideKnownRegionCount++;
          continue;
        }
        terminal.partition[category]=(terminal.partition[category]||0)+1;
      }
    }
    terminal.actionPartitionComplete=!actionInventoryCapped&&terminal.unknownActionCount===0
      &&terminal.unknownOutsideKnownRegionCount===0&&terminal.riskyActionCount===0
      &&Object.values(terminal.partition).reduce((sum,count)=>sum+count,0)===visibleActions;
    const matildaCount=terminal.partition.matildaBanner||0;
    terminal.mudaPartitionReady=terminal.partition.review===1&&terminal.partition.nextItem===1
      &&terminal.partition.cta===1&&terminal.partition.banner===2&&terminal.partition.header===3
      &&(terminal.partition.author||0)>=1&&(terminal.partition.i2i||0)>=1&&(terminal.partition.forYou||0)>=1
      &&(matildaCount===0||matildaCount===1);
    terminal.unknownActionScopeKnown=baseTerminalStructure&&terminal.actionPartitionComplete;
    if(baseTerminalStructure&&headerShapeBounded&&terminal.actionPartitionComplete){
      if(!headerCountsValid||!terminal.mudaPartitionReady){
        return {status:'loading',routeStable:true,slotCount:slots.length,visibleSlots,parts:[],deadEnd:dead,visibleActions,
          counter,counterVisible,toolbarVisible:headerVisible||counterVisible,terminal};
      }
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
