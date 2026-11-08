"""Page-local runtime evidence hook for EbookJapan's observed source draws.

The hook records object identity, draw geometry, reset epochs and bitmap joins
only. It never reads pixel data, fetches a URL, or retains a response body.
CanvasRenderingContext2D methods are observed by the existing D observer; this
module wraps only OffscreenCanvas-specific entry points and dimensions.
"""

from __future__ import annotations

SOURCE_OBSERVER_JS = r"""(() => {
  const key='__ejSourceObserver',statusKey='__ejSourceObserverStatus';
  const host='ebookjapan.yahoo.co.jp',path=/^\/viewer\/purchased\/B[0-9]+\/$/;
  const status=value=>{try{window[statusKey]=value;}catch{}return value;};
  const routeAllowed=()=>window.top===window&&location.hostname===host&&path.test(location.pathname)&&!location.search&&!location.hash;
  if(!routeAllowed())return status({installed:false,reason:'route-not-target'});
  if(window[key])return status({installed:false,reason:'already-installed'});
  if(typeof OffscreenCanvas==='undefined'||typeof ImageBitmap==='undefined')return status({installed:false,reason:'offscreen-api-unavailable'});

  const MAX_ACTIVE_EPOCHS=32,MAX_ROIS=512;
  const canvasStates=new WeakMap(),contextIds=new WeakMap(),imageIds=new WeakMap();
  const bitmapMetadata=new WeakMap(),targetStates=new WeakMap();
  const epochCache=new Map();
  const diagnosticMethodNames=new Set(['arc','beginPath','closePath','fill','stroke','clip','drawImage','getImageData','putImageData',
    'clearRect','fillRect','strokeRect','fillText','strokeText','getTransform','reset','save','restore','translate','rotate',
    'scale','transform','setTransform','resetTransform','setLineDash','isPointInPath','isPointInStroke','createImageData',
    'getContext','transferToImageBitmap','getContextAttributes','isContextLost','getLineDash','measureText','arcTo','ellipse',
    'rect','roundRect','moveTo','lineTo','quadraticCurveTo','bezierCurveTo','createPattern','createLinearGradient',
    'createRadialGradient','createConicGradient','drawFocusIfNeeded','scrollPathIntoView']);
  const diagnosticStateNames=new Set(['globalAlpha','globalCompositeOperation','filter','shadowColor','shadowBlur','shadowOffsetX',
    'shadowOffsetY','imageSmoothingEnabled','imageSmoothingQuality']);
  const diagnosticDimensionNames=new Set(['width','height']);
  let nextObjectId=0,nextEpochId=0,nextTransferSequence=0,cacheEvictions=0,metadataFailures=0;
  let nativeDescriptorsMatch=true,contextWrapperCoverageComplete=false,stopped=false;
  const idFor=(map,value)=>{let id=map.get(value);if(!id){id=++nextObjectId;map.set(value,id);}return id;};
  const finite=n=>typeof n==='number'&&Number.isFinite(n);
  const integer=n=>finite(n)&&Number.isInteger(n);
  const safeEnumList=(value,allowlist)=>Array.isArray(value)?value.filter(name=>allowlist.has(name)).slice(0,32):[];
  const safeInstrumentationDiagnostic=()=>{
    try{
      const captureObserver=window.__ejCaptureObserver;
      const getter=captureObserver?.sourceInstrumentationDiagnostic;
      if(typeof getter!=='function')return null;
      const value=Reflect.apply(getter,captureObserver,[]);
      if(!value||typeof value!=='object')return null;
      const count=value.otherMethodCount;
      return {sourceMethodCoverage:value.sourceMethodCoverage===true,sourceStateCoverage:value.sourceStateCoverage===true,
        offscreenInstall:value.offscreenInstall===true,currentSlotMismatch:value.currentSlotMismatch===true,
        sourceMethodMissing:safeEnumList(value.sourceMethodMissing,diagnosticMethodNames),
        sourceMethodNonNative:safeEnumList(value.sourceMethodNonNative,diagnosticMethodNames),
        offscreenMethodMissing:safeEnumList(value.offscreenMethodMissing,diagnosticMethodNames),
        offscreenMethodNonNative:safeEnumList(value.offscreenMethodNonNative,diagnosticMethodNames),
        stateSetterMissing:safeEnumList(value.stateSetterMissing,diagnosticStateNames),
        stateSetterNonNative:safeEnumList(value.stateSetterNonNative,diagnosticStateNames),
        offscreenStateSetterMissing:safeEnumList(value.offscreenStateSetterMissing,diagnosticStateNames),
        offscreenStateSetterNonNative:safeEnumList(value.offscreenStateSetterNonNative,diagnosticStateNames),
        slotMismatchMethods:safeEnumList(value.slotMismatchMethods,diagnosticMethodNames),
        slotMismatchStateProperties:safeEnumList(value.slotMismatchStateProperties,diagnosticStateNames),
        slotMismatchDimensionProperties:safeEnumList(value.slotMismatchDimensionProperties,diagnosticDimensionNames),
        otherMethodCount:Number.isInteger(count)&&count>=0?Math.min(1024,count):0};
    }catch{return null;}
  };
  const rectOf=values=>Array.isArray(values)&&values.length===8&&values.every(integer)
    &&values[0]>=0&&values[1]>=0&&values[2]>0&&values[3]>0&&values[4]>=0&&values[5]>=0
    &&values[6]>0&&values[7]>0&&values[2]===values[6]&&values[3]===values[7];
  const ownDimensionPropertiesAbsent=canvas=>!Object.prototype.hasOwnProperty.call(canvas,'width')
    &&!Object.prototype.hasOwnProperty.call(canvas,'height');
  const freshCanvasState=canvas=>({canvas,canvasObjectId:idFor(canvasStates,canvas),epoch:0,resetSequence:0,
    currentContext:null,contextPrototype:null,contextObjectId:0,contextKnown:false,contextAttributes:null,drawCalls:0,successfulDraws:0,
    roiRows:[],sourceImages:new Map(),clipCount:0,stateMutationCount:0,contextResetCount:0,contextLossCount:0,
    incompleteReason:'none',lastDrawState:null,latestBitmapId:0,latestTransferSequence:0,
    dirtySinceLatestTransfer:false,
    ownDimensionPropertiesAbsent:ownDimensionPropertiesAbsent(canvas),settersIntact:true});
  const canvasState=canvas=>{let value=canvasStates.get(canvas);if(!value){value=freshCanvasState(canvas);canvasStates.set(canvas,value);}return value;};
  const fail=(state,reason)=>{if(state&&state.incompleteReason==='none')state.incompleteReason=reason;};
  const resetEpoch=(canvas,reason)=>{
    const state=canvasStates.get(canvas);if(!state)return;
    state.epoch++;state.resetSequence++;state.drawCalls=0;state.successfulDraws=0;state.roiRows=[];
    state.sourceImages=new Map();state.clipCount=0;state.stateMutationCount=0;state.contextResetCount=0;
    state.contextLossCount=0;state.lastDrawState=null;state.incompleteReason='none';
    if(reason==='dimension-reset')state.settersIntact=true;
  };
  const resetTransferBatch=canvas=>{
    const state=canvasStates.get(canvas);if(!state)return;
    state.epoch++;state.drawCalls=0;state.successfulDraws=0;state.roiRows=[];
    state.sourceImages=new Map();state.lastDrawState=null;
  };
  const targetState=canvas=>{let value=targetStates.get(canvas);if(!value){value={canvas,canvasObjectId:++nextObjectId,
    bindingToken:0,resetSequence:0,lastDrawSequence:0,lastBinding:null,lastFailureReason:'none',
    width:canvas.width,height:canvas.height};targetStates.set(canvas,value);}return value;};
  const unpinBinding=target=>{target.lastBinding=null;};
  const invalidateTarget=(canvas,reason)=>{
    const target=targetState(canvas);unpinBinding(target);target.bindingToken++;target.resetSequence++;
    target.lastBinding=null;target.lastFailureReason=reason;target.width=canvas.width;target.height=canvas.height;
  };
  const sourceDimensions=source=>{
    if(source instanceof HTMLImageElement)return {kind:'HTMLImageElement',width:source.naturalWidth,height:source.naturalHeight};
    if(source instanceof HTMLCanvasElement||source instanceof OffscreenCanvas)return {kind:source.constructor.name,width:source.width,height:source.height};
    if(source instanceof ImageBitmap)return {kind:'ImageBitmap',width:source.width,height:source.height};
    return {kind:'unknown',width:0,height:0};
  };
  const defaultDrawState=(context,state)=>{
    let transform=null,attributes=null;
    try{const matrix=context.getTransform();transform=[matrix.a,matrix.b,matrix.c,matrix.d,matrix.e,matrix.f];}catch{metadataFailures++;}
    try{if(typeof context.getContextAttributes==='function')attributes=context.getContextAttributes();}catch{metadataFailures++;}
    const cleanAttributes=attributes?{
      alpha:attributes.alpha===true,colorSpace:typeof attributes.colorSpace==='string'?attributes.colorSpace:'',
      colorType:typeof attributes.colorType==='string'?attributes.colorType:'',
      desynchronized:attributes.desynchronized===false?false:null,
      willReadFrequently:attributes.willReadFrequently===false?false:null
    }:null;
    const shadowColor=String(context.shadowColor||'');
    const filterValue=context.filter==='none'?'none':'non-default';
    const stateSnapshot={contextAttributes:cleanAttributes,transform,globalAlpha:context.globalAlpha,
      compositeOperation:String(context.globalCompositeOperation||''),filterValue,
      shadowColor,shadowBlur:context.shadowBlur,shadowOffsetX:context.shadowOffsetX,shadowOffsetY:context.shadowOffsetY,
      imageSmoothingEnabled:context.imageSmoothingEnabled===true,imageSmoothingQuality:String(context.imageSmoothingQuality||''),
      clipCount:state.clipCount,stateMutationCount:state.stateMutationCount,contextResetCount:state.contextResetCount,
      contextLossCount:state.contextLossCount,criticalWrappersMatch:contextWrapperCoverageComplete&&nativeDescriptorsMatch};
    const identity=Array.isArray(transform)&&transform.length===6&&transform.every((v,i)=>finite(v)&&Math.abs(v-[1,0,0,1,0,0][i])<=1e-6);
    const eligible=!!cleanAttributes&&cleanAttributes.alpha&&cleanAttributes.colorSpace==='srgb'
      &&cleanAttributes.colorType==='unorm8'&&!cleanAttributes.desynchronized&&!cleanAttributes.willReadFrequently
      &&identity&&stateSnapshot.globalAlpha===1&&stateSnapshot.compositeOperation==='source-over'
      &&stateSnapshot.filterValue==='none'&&['rgba(0, 0, 0, 0)','transparent'].includes(shadowColor)
      &&stateSnapshot.shadowBlur===0&&stateSnapshot.shadowOffsetX===0&&stateSnapshot.shadowOffsetY===0
      &&stateSnapshot.imageSmoothingEnabled&&stateSnapshot.imageSmoothingQuality==='low'
      &&state.clipCount===0&&state.stateMutationCount===0&&state.contextResetCount===0&&state.contextLossCount===0
      &&stateSnapshot.criticalWrappersMatch;
    return {state:stateSnapshot,eligible};
  };
  const recordContextReturn=(canvas,args,didThrow,result)=>{
    if(!routeAllowed()||!(canvas instanceof OffscreenCanvas))return;
    const state=canvasState(canvas);
    if(didThrow){state.contextKnown=false;fail(state,'offscreen-get-context-threw');return;}
    if(typeof args?.[0]!=='string'||args[0]!=='2d'||!result||result.canvas!==canvas){
      state.contextKnown=false;fail(state,'offscreen-context-type-unknown');return;
    }
    const prototype=Object.getPrototypeOf(result);
    if(!prototype||typeof prototype!=='object'||(state.contextPrototype&&state.contextPrototype!==prototype)){
      state.contextKnown=false;fail(state,'offscreen-context-prototype-unknown');return;
    }
    const old=state.currentContext;
    if(old&&old!==result){state.contextKnown=false;fail(state,'offscreen-current-context-changed');return;}
    state.currentContext=result;state.contextPrototype=prototype;state.contextObjectId=idFor(contextIds,result);state.contextKnown=true;
    if(state.epoch===0)state.epoch=1;
    state.contextAttributes=defaultDrawState(result,state).state.contextAttributes;
    if(!state.contextAttributes)fail(state,'offscreen-context-attributes-unavailable');
  };
  const recordSourceContextCall=(name,context,args,didThrow)=>{
    if(!routeAllowed()||!(context?.canvas instanceof OffscreenCanvas))return;
    const state=canvasState(context.canvas);
    if(!state.contextKnown||state.currentContext!==context){fail(state,'offscreen-context-identity-unknown');return;}
    if(name==='clip'){state.dirtySinceLatestTransfer=true;state.clipCount++;fail(state,'offscreen-clip-observed');return;}
    if(name==='reset'){
      state.dirtySinceLatestTransfer=true;
      if(!didThrow)resetEpoch(context.canvas,'context-reset');
      else fail(state,'offscreen-context-reset-threw');
      return;
    }
    if(name==='getTransform'||name==='getContextAttributes')return;
    if(name==='drawImage'){
      state.drawCalls++;state.dirtySinceLatestTransfer=true;
      if(didThrow){fail(state,'offscreen-draw-threw');return;}
      const dimensions=sourceDimensions(args?.[0]);
      const values=Array.isArray(args)?args.slice(1):[];
      const geometryKnown=values.length===8&&rectOf(values)
        &&values[0]+values[2]<=dimensions.width&&values[1]+values[3]<=dimensions.height
        &&values[4]+values[6]<=context.canvas.width&&values[5]+values[7]<=context.canvas.height;
      const isImage=args?.[0] instanceof HTMLImageElement;
      const currentSrc=isImage?String(args[0].currentSrc||''):'';
      const imageId=isImage?idFor(imageIds,args[0]):0;
      const drawState=defaultDrawState(context,state);
      state.lastDrawState=drawState.state;state.successfulDraws++;
      if(!isImage||!currentSrc)fail(state,'offscreen-image-source-unknown');
      if(!geometryKnown)fail(state,'offscreen-roi-geometry-unknown');
      if(!drawState.eligible)fail(state,'offscreen-draw-state-unknown');
      if(state.roiRows.length>=MAX_ROIS){fail(state,'offscreen-roi-cap-exceeded');return;}
      const row=geometryKnown?values.map(value=>Number(value)):null;
      if(!row){fail(state,'offscreen-roi-geometry-unknown');return;}
      state.roiRows.push(row);
      if(isImage){
        state.sourceImages.set(imageId,{image:args[0],currentSrc,width:dimensions.width,height:dimensions.height});
      }
      return;
    }
    state.dirtySinceLatestTransfer=true;
    if(didThrow)fail(state,'offscreen-context-method-threw');
    state.stateMutationCount++;fail(state,'offscreen-unknown-context-method');
  };
  const addEpoch=(metadata)=>{
    if(epochCache.size>=MAX_ACTIVE_EPOCHS){
      const evictKey=epochCache.keys().next().value;
      if(evictKey===undefined){metadata.incompleteReason='active-epoch-cache-full';return false;}
      epochCache.delete(evictKey);cacheEvictions++;
    }
    epochCache.set(metadata.epochId,metadata);return true;
  };
  const recordTransfer=(canvas,didThrow,bitmap)=>{
    if(!routeAllowed()||!(canvas instanceof OffscreenCanvas))return;
    const state=canvasState(canvas);
    if(didThrow){fail(state,'offscreen-transfer-threw');return;}
    const epochId=++nextEpochId,transferSequence=++nextTransferSequence,bitmapObjectId=++nextObjectId;
    const metadata={epochId,transferSequence,bitmapObjectId,sourceCanvasObjectId:state.canvasObjectId,sourceCanvas:canvas,
      sourceContextObjectId:state.contextObjectId,epoch:state.epoch,resetSequence:state.resetSequence,
      width:canvas.width,height:canvas.height,drawCalls:state.drawCalls,successfulDraws:state.successfulDraws,
      roiRows:state.roiRows.map(row=>row.slice()),sourceImages:[...state.sourceImages.entries()].map(([imageId,value])=>({
        imageId,image:value.image,currentSrc:value.currentSrc,width:value.width,height:value.height})),
      drawState:state.lastDrawState,clipCount:state.clipCount,stateMutationCount:state.stateMutationCount,
      contextResetCount:state.contextResetCount,contextLossCount:state.contextLossCount,
      contextKnown:state.contextKnown&&state.currentContext!==null,ownDimensionPropertiesAbsent:ownDimensionPropertiesAbsent(canvas),
      settersIntact:state.settersIntact&&nativeDescriptorsMatch,wrapperCoverageComplete:contextWrapperCoverageComplete,
      incompleteReason:state.incompleteReason};
    bitmapMetadata.set(bitmap,metadata);state.latestBitmapId=bitmapObjectId;state.latestTransferSequence=transferSequence;
    addEpoch(metadata);
     resetTransferBatch(canvas);state.dirtySinceLatestTransfer=false;
  };
  const recordTargetDraw=(context,args,didThrow,dState)=>{
    if(!routeAllowed()||!(context?.canvas instanceof HTMLCanvasElement))return;
    const canvas=context.canvas,target=targetState(canvas);
    unpinBinding(target);target.bindingToken++;target.lastDrawSequence++;target.lastBinding=null;
    target.lastFailureReason='target-draw-unproven';target.width=canvas.width;target.height=canvas.height;
    if(didThrow){target.lastFailureReason='target-draw-threw';return;}
    const bitmap=args?.[0],metadata=bitmap instanceof ImageBitmap?bitmapMetadata.get(bitmap):null;
    if(!metadata)return;
    const naturalFull=args.length===3&&args[1]===0&&args[2]===0
      &&metadata.width===canvas.width&&metadata.height===canvas.height;
    if(!naturalFull){target.lastFailureReason='target-draw-geometry-unknown';return;}
    const cached=epochCache.get(metadata.epochId)===metadata;
    const sourceState=canvasStates.get(metadata.sourceCanvas);
    const latest=sourceState&&sourceState.latestBitmapId===metadata.bitmapObjectId
      &&sourceState.latestTransferSequence===metadata.transferSequence;
    const binding={epochId:metadata.epochId,bitmapObjectId:metadata.bitmapObjectId,
      sourceCanvasObjectId:metadata.sourceCanvasObjectId,sourceContextObjectId:metadata.sourceContextObjectId,
      sourceEpoch:metadata.epoch,sourceResetSequence:metadata.resetSequence,
      transferSequence:metadata.transferSequence,targetCanvasObjectId:target.canvasObjectId,
      targetBindingToken:target.bindingToken,targetResetSequence:target.resetSequence,
      targetWidth:canvas.width,targetHeight:canvas.height,targetDrawSequence:target.lastDrawSequence,
      dDrawGeneration:dState?.drawGeneration??null,dSuccessfulDraws:dState?.successfulDraws??null,
      dLastFullDraw:dState?.lastFullDraw===true,dResetObserved:dState?.resetObserved===true,
      dClipCalls:dState?.clipCalls??null,cachePresent:cached,latestTransfer:!!latest,
      proofKnown:cached&&latest&&metadata.incompleteReason==='none'&&metadata.contextKnown
        &&metadata.ownDimensionPropertiesAbsent&&metadata.settersIntact&&metadata.wrapperCoverageComplete
        &&Array.isArray(metadata.roiRows)&&metadata.roiRows.length>0,sourceCanvas:metadata.sourceCanvas};
    target.lastBinding=binding;target.lastFailureReason='none';
  };
  const currentSrcStatus=metadata=>metadata.sourceImages.map(value=>({imageId:value.imageId,
    width:value.width,height:value.height,currentSrcPresent:!!value.currentSrc,
    currentSrcUnchanged:!!value.image&&String(value.image.currentSrc||'')===value.currentSrc,
    dimensionsUnchanged:!!value.image&&value.image.naturalWidth===value.width&&value.image.naturalHeight===value.height}));
  const sourceImageReferencesAreCurrent=metadata=>!!metadata&&metadata.sourceImages.length>0
    &&metadata.sourceImages.every(value=>!!value.image&&String(value.image.currentSrc||'')===value.currentSrc
      &&value.image.naturalWidth===value.width&&value.image.naturalHeight===value.height);
  const sourceDescriptorsAreCurrent=()=>offscreenProto.transferToImageBitmap===transferWrapper
    &&['width','height'].every(name=>Object.getOwnPropertyDescriptor(offscreenProto,name)?.set===dimensionWrappers[name]);
  const targetSnapshot=canvas=>{
    if(!routeAllowed()||!(canvas instanceof HTMLCanvasElement))return null;
    const target=targetState(canvas),observer=window.__ejCaptureObserver;
    let dState=null;try{dState=observer?.statusFor?.(canvas)||null;}catch{metadataFailures++;}
    const binding=target.lastBinding;
    const cachePresent=!!binding&&epochCache.has(binding.epochId);
    const stateKnown=!!binding&&binding.proofKnown&&cachePresent
      &&target.bindingToken===binding.targetBindingToken&&target.resetSequence===binding.targetResetSequence
      &&canvas.width===binding.targetWidth&&canvas.height===binding.targetHeight
      &&target.lastDrawSequence===binding.targetDrawSequence;
    const dJoin=!!binding&&!!dState&&dState.drawGeneration===binding.dDrawGeneration
      &&dState.successfulDraws===binding.dSuccessfulDraws&&dState.lastFullDraw===true
      &&dState.resetObserved===false&&dState.clipCalls===0&&dState.overflow===false&&dState.metadataFailures===0;
    const metadata=binding?epochCache.get(binding.epochId):null;
    const liveSourceState=metadata?canvasStates.get(metadata.sourceCanvas):null;
    const latestTransfer=!!liveSourceState&&liveSourceState.latestBitmapId===binding?.bitmapObjectId
      &&liveSourceState.latestTransferSequence===binding?.transferSequence
      &&liveSourceState.dirtySinceLatestTransfer===false;
    const liveSourceIsCurrent=!!metadata&&!!liveSourceState&&liveSourceState.contextKnown
      &&liveSourceState.contextObjectId===binding?.sourceContextObjectId
      &&liveSourceState.ownDimensionPropertiesAbsent&&ownDimensionPropertiesAbsent(metadata.sourceCanvas)
      &&liveSourceState.settersIntact&&metadata.sourceCanvas.width===metadata.width
      &&metadata.sourceCanvas.height===metadata.height;
    const instrumentationCurrent=sourceDescriptorsAreCurrent()
      &&observer?.sourceInstrumentationIsCurrent?.()===true;
    const sourceImagesCurrent=sourceImageReferencesAreCurrent(metadata);
    const reason=!binding?target.lastFailureReason:!cachePresent?'source-epoch-evicted'
      :!latestTransfer?'source-bitmap-stale':!binding.proofKnown?(metadata?.incompleteReason||'source-proof-incomplete')
      :!liveSourceIsCurrent?'source-context-or-dimensions-changed':!instrumentationCurrent?'source-observer-wrapper-mismatch'
      :!sourceImagesCurrent?'source-image-reference-changed'
      :!dJoin?'d-draw-join-stale':'none';
    return {installed:true,routeMatches:routeAllowed(),health:{installed:!stopped,cacheEvictions,
      activeEpochs:epochCache.size,metadataFailures,nativeDescriptorsMatch:sourceDescriptorsAreCurrent(),
      contextWrapperCoverageComplete,instrumentationCurrent,instrumentationDiagnostic:safeInstrumentationDiagnostic()},
      target:{canvasObjectId:target.canvasObjectId,width:canvas.width,height:canvas.height,
        bindingToken:target.bindingToken,resetSequence:target.resetSequence,lastDrawSequence:target.lastDrawSequence,
        ownDimensionPropertiesAbsent:ownDimensionPropertiesAbsent(canvas)},
      binding:binding?{epochId:binding.epochId,bitmapObjectId:binding.bitmapObjectId,
        sourceCanvasObjectId:binding.sourceCanvasObjectId,sourceContextObjectId:binding.sourceContextObjectId,
        sourceEpoch:binding.sourceEpoch,sourceResetSequence:binding.sourceResetSequence,
        transferSequence:binding.transferSequence,targetCanvasObjectId:binding.targetCanvasObjectId,
        targetBindingToken:binding.targetBindingToken,targetResetSequence:binding.targetResetSequence,
        targetWidth:binding.targetWidth,targetHeight:binding.targetHeight,targetDrawSequence:binding.targetDrawSequence,
        dDrawGeneration:binding.dDrawGeneration,dSuccessfulDraws:binding.dSuccessfulDraws,
        dLastFullDraw:binding.dLastFullDraw,dResetObserved:binding.dResetObserved,dClipCalls:binding.dClipCalls,
        latestTransfer,current:stateKnown&&dJoin&&latestTransfer&&liveSourceIsCurrent&&instrumentationCurrent&&sourceImagesCurrent,reason,
        source:{epochId:binding.epochId,bitmapObjectId:binding.bitmapObjectId,
          sourceCanvasObjectId:binding.sourceCanvasObjectId,sourceContextObjectId:binding.sourceContextObjectId,
          epoch:binding.sourceEpoch,resetSequence:binding.sourceResetSequence,
          transferSequence:binding.transferSequence,width:metadata?.width??null,height:metadata?.height??null,
          drawCalls:metadata?.drawCalls??null,successfulDraws:metadata?.successfulDraws??null,
          roiRows:metadata?.roiRows?.map(row=>row.slice())??null,clipCount:metadata?.clipCount??null,
          stateMutationCount:metadata?.stateMutationCount??null,contextResetCount:metadata?.contextResetCount??null,
          contextLossCount:metadata?.contextLossCount??null,incompleteReason:metadata?.incompleteReason??'source-epoch-evicted',
          contextKnown:metadata?.contextKnown??false,ownDimensionPropertiesAbsent:metadata?.ownDimensionPropertiesAbsent??false,
          settersIntact:metadata?.settersIntact??false,wrapperCoverageComplete:metadata?.wrapperCoverageComplete??false,
          drawState:metadata?.drawState??null,sourceImages:metadata?currentSrcStatus(metadata):null}}
        :null,dState:dState?{drawGeneration:dState.drawGeneration,successfulDraws:dState.successfulDraws,
          mutationCount:dState.mutationCount,clipCalls:dState.clipCalls,lastFullDraw:dState.lastFullDraw,
          resetObserved:dState.resetObserved,contextIs2d:dState.contextIs2d,overflow:dState.overflow,
          metadataFailures:dState.metadataFailures}:null};
  };
  const recordStateMutation=(context,name,didThrow)=>{
    if(!routeAllowed()||!(context?.canvas instanceof OffscreenCanvas))return;
    const state=canvasState(context.canvas);state.dirtySinceLatestTransfer=true;state.stateMutationCount++;
    fail(state,didThrow?'offscreen-context-state-setter-threw':'offscreen-context-state-mutated');
    if(typeof name==='string'&&name.toLowerCase().includes('clip'))state.clipCount++;
  };
  const recordContextLoss=canvas=>{
    if(!routeAllowed()||!(canvas instanceof OffscreenCanvas))return;
    const state=canvasState(canvas);state.contextLossCount++;state.contextKnown=false;
    fail(state,'offscreen-context-loss-observed');
  };
  const setContextWrapperCoverage=value=>{contextWrapperCoverageComplete=value===true;};
  const expectedNative=fn=>{try{return typeof fn==='function'&&/\[native code\]/.test(Function.prototype.toString.call(fn));}catch{return false;}};
  const offscreenProto=OffscreenCanvas.prototype;
  const getContextDescriptor=Object.getOwnPropertyDescriptor(offscreenProto,'getContext');
  const transferDescriptor=Object.getOwnPropertyDescriptor(offscreenProto,'transferToImageBitmap');
  const widthDescriptors=Object.fromEntries(['width','height'].map(name=>[name,Object.getOwnPropertyDescriptor(offscreenProto,name)]));
  const originals={transferToImageBitmap:transferDescriptor?.value};
  const required=[getContextDescriptor,transferDescriptor,widthDescriptors.width,widthDescriptors.height];
  nativeDescriptorsMatch=required.every(desc=>desc&&expectedNative(desc.value||desc.set));
  if(transferDescriptor&&!transferDescriptor.configurable)nativeDescriptorsMatch=false;
  for(const descriptor of Object.values(widthDescriptors))if(!descriptor?.configurable)nativeDescriptorsMatch=false;
  if(!nativeDescriptorsMatch)return status({installed:false,reason:'offscreen-native-descriptor-conflict'});
  const transferWrapper=function(...args){
    let result,didThrow=false,thrown;
    try{result=Reflect.apply(originals.transferToImageBitmap,this,args);}catch(error){didThrow=true;thrown=error;}
    try{recordTransfer(this,didThrow,result);}catch{metadataFailures++;}
    if(didThrow)throw thrown;return result;
  };
  Object.defineProperty(offscreenProto,'transferToImageBitmap',{...transferDescriptor,value:transferWrapper});
  const dimensionWrappers={};
  for(const name of ['width','height']){
    const descriptor=widthDescriptors[name],originalSet=descriptor.set;
    dimensionWrappers[name]=function(value){
      let result,didThrow=false,thrown;
      try{result=Reflect.apply(originalSet,this,[value]);}catch(error){didThrow=true;thrown=error;}
      if(!didThrow&&routeAllowed()&&this instanceof OffscreenCanvas){
        try{const state=canvasState(this);state.dirtySinceLatestTransfer=true;resetEpoch(this,'dimension-reset');
          state.ownDimensionPropertiesAbsent=ownDimensionPropertiesAbsent(this);}catch{metadataFailures++;}
      }
      if(didThrow)throw thrown;return result;
    };
    Object.defineProperty(offscreenProto,name,{...descriptor,set:dimensionWrappers[name]});
  }
  const onContextLoss=event=>{if(event?.type==='contextlost')recordContextLoss(event.currentTarget);};
  const installLossListener=canvas=>{try{canvas.addEventListener('contextlost',onContextLoss);canvas.addEventListener('contextrestored',onContextLoss);}catch{metadataFailures++;}};
  const observer={
    recordContextReturn,recordSourceContextCall,recordTargetDraw,recordStateMutation,
    invalidateTarget,recordContextLoss,setContextWrapperCoverage,
    targetSnapshot,
    recordInstrumentationFailure(){nativeDescriptorsMatch=false;metadataFailures++;},
    health(){return {installed:!stopped&&routeAllowed(),routeMatches:routeAllowed(),nativeDescriptorsMatch,
      contextWrapperCoverageComplete,activeEpochs:epochCache.size,cacheEvictions,metadataFailures,
      maxActiveEpochs:MAX_ACTIVE_EPOCHS,maxRoisPerEpoch:MAX_ROIS,
      instrumentationCurrent:window.__ejCaptureObserver?.sourceInstrumentationIsCurrent?.()===true,
      instrumentationDiagnostic:safeInstrumentationDiagnostic()};},
    stop(){
      stopped=true;
      const restored={transferToImageBitmap:false,width:false,height:false};
      if(offscreenProto.transferToImageBitmap===transferWrapper){Object.defineProperty(offscreenProto,'transferToImageBitmap',transferDescriptor);restored.transferToImageBitmap=offscreenProto.transferToImageBitmap===originals.transferToImageBitmap;}
      for(const name of ['width','height']){const current=Object.getOwnPropertyDescriptor(offscreenProto,name);if(current?.set===dimensionWrappers[name]){Object.defineProperty(offscreenProto,name,widthDescriptors[name]);restored[name]=Object.getOwnPropertyDescriptor(offscreenProto,name)?.set===widthDescriptors[name].set;}}
      status({installed:false,stopped:true,restored});return {restored};
    }
  };
  const getCanvasState=canvas=>{const value=canvasState(canvas);installLossListener(canvas);return value;};
  // Expose only bounded, non-sensitive object metadata. Raw currentSrc stays in
  // this closure and never enters the returned snapshot.
  observer.recordContextReturn=(canvas,args,didThrow,result)=>{if(canvas instanceof OffscreenCanvas)getCanvasState(canvas);recordContextReturn(canvas,args,didThrow,result);};
  observer.recordSourceContextCall=(name,context,args,didThrow)=>{if(context?.canvas instanceof OffscreenCanvas)getCanvasState(context.canvas);recordSourceContextCall(name,context,args,didThrow);};
  observer.recordTransfer=(canvas,didThrow,bitmap)=>{getCanvasState(canvas);recordTransfer(canvas,didThrow,bitmap);};
  window[key]=observer;return status({installed:true,routeMatches:true,maxActiveEpochs:MAX_ACTIVE_EPOCHS,maxRoisPerEpoch:MAX_ROIS});
})();"""

