"""Fail-closed direct-free Viewer for the observed HERO'S WEB layout."""

from __future__ import annotations

import asyncio
import base64
import copy
import re
from dataclasses import dataclass
from pathlib import PurePosixPath
from urllib.parse import urlsplit

from playwright.async_api import Error as PlaywrightError
from playwright.async_api import Page

from screenshot_crawler.core.access_guard import AccessProfile
from screenshot_crawler.core.capture import CaptureResult, capture_png_bytes
from screenshot_crawler.core.errors import (
    AccessStopError,
    PageChangeTimeoutError,
    UnknownPageStateError,
    UnsupportedAccessStrategyError,
)
from screenshot_crawler.core.models import AccessStrategy, ContentContext, ContentIdentity
from screenshot_crawler.core.state import PageState
from screenshot_crawler.site_adapters.base import SiteAdapter
from screenshot_crawler.site_adapters.herosweb.access import (
    herosweb_access_profile,
    is_herosweb_relevant_host,
)
from screenshot_crawler.site_adapters.herosweb.discovery import (
    DOM_TIMEOUT_MS,
    RANGE_PACING_MS,
    STABILITY_INTERVAL_MS,
    _auth_header_script,
    _CurrentDocumentAuth,
    _positive_auth_header,
    _safe_route_error_category,
    _snapshot_script,
    _validate_snapshot,
    _validate_work_header_snapshot,
    parse_herosweb_episode_url,
    parse_herosweb_work_url,
)
from screenshot_crawler.site_adapters.herosweb.native_capture import (
    decode_native_candidates,
    encode_native_candidates,
)

BASE_URL = "https://heros-web.com"
EPISODE_ID_RE = re.compile(r"^[0-9a-f]{13}$")
EXTERNAL_ID_RE = re.compile(r"^(?P<work>[0-9a-f]{13}):(?P<episode>[0-9a-f]{13})$")
EXPECTED_READ_PATH_RE = re.compile(r"^/api/episodes/(?P<episode>[0-9a-f]{13})/read$")
EXPECTED_READ_COMPLETED_PATH_RE = re.compile(
    r"^/api/episodes/(?P<episode>[0-9a-f]{13})/readCompleted$"
)

MAX_PREFLIGHT_RANGES = 3
MAX_BODY_PAGES = 1_000
_OBSERVED_RESUMED_PR_PROFILES = frozenset(
    {
        (17, 10, 17, 13),
        (45, 38, 45, 41),
    }
)
MAX_VIEWER_SETTLE_SECONDS = 20.0
MAX_PREFLIGHT_SECONDS = 180.0
AUTH_HEADER_SETTLE_SECONDS = 5.0
PAGE_CHANGE_TIMEOUT_MS = 20_000
POLL_INTERVAL_MS = 100
SEEK_SETTLE_INTERVAL_MS = 200

def _spread_seek_max(wrapper_count: int) -> int:
    # The native range enumerates odd-valued spread starts. An even wrapper
    # count ends with the observed Good/Last pair, rather than a lone Last.
    return 2 * ((wrapper_count - 1) // 2) + 1


_ROOT_REQUIRED_MODES = frozenset(
    {
        "mode-h",
        "mode-dir-rtl",
        "mode-nav-dir-rtl",
        "mode-spread",
        "mode-pc",
        "mode-has-good-page",
        "mode-skip-next-confirm",
        "mode-disable-toc",
        "mode-app-link-comimaga",
        "mode-no-toc",
        "mode-use-glimpse-bottom",
        "mode-glimpse-bottom",
        "mode-has-pr",
    }
)
_ROOT_OPTIONAL_FEATURE_MODES = frozenset(
    {"mode-has-app-link", "mode-has-comic-info"}
)
_ROOT_OPTIONAL_NAVIGATION_MODES = frozenset(
    {"mode-has-first-ep", "mode-has-prev-ep", "mode-has-next-ep"}
)
_ROOT_STRUCTURAL_MODES = _ROOT_REQUIRED_MODES | _ROOT_OPTIONAL_NAVIGATION_MODES
_ROOT_DYNAMIC_MODES = frozenset(
    {
        "mode-first-page",
        "mode-top-pr-page",
        "mode-pr-page",
        "mode-last-page",
        "mode-nav-open",
        "mode-ci-page",
    }
)
_BODY_STATE_MODES = frozenset(
    {"mode-loaded", "mode-rendered", "mode-loading", "mode-req-render"}
)
_KNOWN_READ_TELEMETRY = frozenset({"/api/missions"})


async def _fetch_main_frame_response_without_redirect(route):
    """Fetch one exact document request without following an HTTP redirect."""

    return await route.fetch(
        max_redirects=0,
        max_retries=0,
        timeout=PAGE_CHANGE_TIMEOUT_MS,
    )


_OBSERVER_INIT_SCRIPT = r"""(() => {
  if (window.__hwebCaptureObserver) return;
  const ids = new WeakMap();
  const epochs = new WeakMap();
  const generations = new WeakMap();
  const histories = new WeakMap();
  const historyOverflow = new WeakSet();
  const clipCounts = new WeakMap();
  const nativeCandidates = new Map();
  const MAX_HISTORY = 24;
  const MAX_NATIVE_PIXELS = 3000000;
  const MAX_NATIVE_TARGETS = 2;
  let nextId = 1;
  let totalDraws = 0;
  let nativeMaterializationInFlight = false;
  let nativeCandidateSpreadKey = null;
  const nodeId = node => {
    if (!node || (typeof node !== 'object' && typeof node !== 'function')) return null;
    let id = ids.get(node);
    if (!id) { id = nextId++; ids.set(node, id); }
    return id;
  };
  const epoch = canvas => epochs.get(canvas) || 0;
  const generation = canvas => generations.get(canvas) || 0;
  const slotOf = canvas => {
    if (!(canvas instanceof HTMLCanvasElement)) return null;
    const pages = document.querySelector('.-cv-pages');
    const wrapper = canvas.closest('.-cv-page');
    if (!pages || !wrapper || wrapper.parentElement !== pages) return null;
    return [...pages.children].indexOf(wrapper);
  };
  const rectOf = node => {
    const value = node.getBoundingClientRect();
    return {x:value.x,y:value.y,width:value.width,height:value.height};
  };
  const classTokensOf = node => (node.getAttribute('class')||'').split(/\s+/).filter(Boolean);
  const ROOT_REQUIRED_MODES = new Set([
    'mode-h','mode-dir-rtl','mode-nav-dir-rtl','mode-spread','mode-pc',
    'mode-has-good-page','mode-skip-next-confirm','mode-disable-toc',
    'mode-app-link-comimaga','mode-no-toc','mode-use-glimpse-bottom',
    'mode-glimpse-bottom','mode-has-pr'
  ]);
  const ROOT_ALLOWED_MODES = new Set([
    ...ROOT_REQUIRED_MODES,'mode-has-first-ep','mode-has-prev-ep','mode-has-next-ep',
    'mode-has-app-link','mode-has-comic-info','mode-first-page','mode-top-pr-page',
    'mode-pr-page','mode-last-page','mode-nav-open','mode-ci-page','-cv',
    'mode-lang-ja','mode-vh-change'
  ]);
  const ROOT_INITIAL_DRAW_REQUIRED_MODES = new Set(
    [...ROOT_REQUIRED_MODES].filter(mode => mode !== 'mode-has-pr')
  );
  const BODY_STATE_MODES = new Set(['mode-loaded','mode-rendered','mode-loading','mode-req-render']);
  const frozenLayoutForCurrentDocument = () => {
    const identity = documentIdentity();
    if (!identity.episodeId || !identity.workPath || identity.canonical.length !== 1 ||
        identity.canonical[0] !== identity.url || !identity.url.startsWith('https://heros-web.com/episodes/'))
      return null;
    const roots = [...document.querySelectorAll('.-cv')];
    const wraps = [...document.querySelectorAll('.-cv-pages-wrap')];
    const pageRoots = [...document.querySelectorAll('.-cv-pages')];
    const inputs = [...document.querySelectorAll('input[type="range"]')];
    if (roots.length !== 1 || wraps.length !== 1 || pageRoots.length !== 1 || inputs.length !== 1 ||
        !roots[0].contains(wraps[0]) || !wraps[0].contains(pageRoots[0]) ||
        document.querySelectorAll('.-cv iframe, .-cv-pages iframe').length !== 0) return null;
    const root = roots[0], pagesWrap = wraps[0], pages = pageRoots[0], input = inputs[0];
    const allowPendingPrShell = !input.disabled && input.min === '1' && input.step === '2' &&
      input.value === input.max;
    const rootClasses = new Set(classTokensOf(root));
    const drawRequiredModes = allowPendingPrShell ? ROOT_INITIAL_DRAW_REQUIRED_MODES : ROOT_REQUIRED_MODES;
    if ([...drawRequiredModes].some(mode => !rootClasses.has(mode)) ||
        [...rootClasses].some(mode => !ROOT_ALLOWED_MODES.has(mode))) return null;
    const wrappers = [...pages.children];
    if (wrappers.length < 2 || wrappers.length > 1006) return null;
    const roles = [];
    const wrapperNodeIds = [];
    const bodySlots = [], prSlots = [], ciSlots = [], goodSlots = [], lastSlots = [];
    for (let index=0; index<wrappers.length; index++) {
      const wrapper = wrappers[index];
      if (wrapper.tagName !== 'DIV') return null;
      const classes = new Set(classTokensOf(wrapper));
      if (!classes.has('-cv-page')) return null;
      const markers = ['mode-pr','mode-ci','mode-good','mode-last'].filter(mode => classes.has(mode));
      if (markers.length > 1) return null;
      let role;
      if (markers[0] === 'mode-pr') {
        const expected = index === 0
          ? ['-cv-page','mode-empty','mode-pr','mode-top-pr']
          : ['-cv-page','mode-empty','mode-pr'];
        if (classes.size !== expected.length || expected.some(mode => !classes.has(mode))) return null;
        if (index === 0) role = 'lead_pr';
        else { role='pr'; prSlots.push(index); }
      } else if (markers[0] === 'mode-ci') {
        if (classes.size !== 2 || !classes.has('-cv-page')) return null;
        role='ci'; ciSlots.push(index);
      } else if (markers[0] === 'mode-good') {
        if (classes.size !== 2 || !classes.has('-cv-page')) return null;
        role='good'; goodSlots.push(index);
      } else if (markers[0] === 'mode-last') {
        if (classes.size !== 2 || !classes.has('-cv-page')) return null;
        role='last'; lastSlots.push(index);
      } else {
        if ([...classes].some(mode => mode !== '-cv-page' && !BODY_STATE_MODES.has(mode))) return null;
        role='body'; bodySlots.push(index);
      }
      roles.push(role);
      wrapperNodeIds.push(nodeId(wrapper));
    }
    if (roles[0] !== 'lead_pr' || ciSlots.length !== 1 || goodSlots.length !== 1 ||
        lastSlots.length !== 1 || prSlots.length !== 3 || bodySlots.length < 1 ||
        bodySlots.length > 1000) return null;
    const ciSlot=ciSlots[0], goodSlot=goodSlots[0], lastSlot=lastSlots[0];
    if (bodySlots.some((slot,index) => slot !== index+1) ||
        prSlots.some((slot,index) => slot !== ciSlot+index+1) ||
        goodSlot !== ciSlot+4 || lastSlot !== ciSlot+5 || lastSlot !== wrappers.length-1) return null;
    const parseInteger = value => /^\d+$/.test(String(value)) ? Number(value) : NaN;
    const seekMin=parseInteger(input.min), seekMax=parseInteger(input.max),
      seekStep=parseInteger(input.step), seekValue=parseInteger(input.value);
    const expectedSeekMax = 2 * Math.floor((wrappers.length - 1) / 2) + 1;
    if (input.disabled || seekMin !== 1 || seekStep !== 2 || seekMax !== expectedSeekMax ||
        !Number.isInteger(seekValue) || seekValue < seekMin || seekValue > seekMax ||
        (seekValue-seekMin)%seekStep || (seekMax-seekMin)%seekStep) return null;
    const rootStructuralModes = [...rootClasses].filter(mode =>
      ROOT_REQUIRED_MODES.has(mode) || ['mode-has-first-ep','mode-has-prev-ep','mode-has-next-ep'].includes(mode)
    ).sort();
    const layout = {
      episodeId:identity.episodeId,workPath:identity.workPath,url:identity.url,canonical:identity.canonical,
      rootNodeId:nodeId(root),pagesWrapNodeId:nodeId(pagesWrap),pagesRootNodeId:nodeId(pages),
      wrapperNodeIds,roles,bodySlots,ciSlot,prSlots,goodSlot,lastSlot,
      seekNodeId:nodeId(input),seekMin,seekMax,seekStep,rootStructuralModes
    };
    const candidateRootModes = rootStructuralModes.includes('mode-has-pr')
      ? rootStructuralModes : [...rootStructuralModes,'mode-has-pr'].sort();
    const layoutKey=JSON.stringify({...layout,rootStructuralModes:candidateRootModes});
    const pairStart=((seekMax-seekValue)/seekStep)*2;
    if (allowPendingPrShell && pairStart !== 0) return null;
    const pairSlots=wrappers.slice(pairStart,pairStart+2).map((_node,index)=>pairStart+index);
    const spreadKey=JSON.stringify({layoutKey,seekValue,pairSlots});
    return {layout,layoutKey,seekValue,seekNodeId:layout.seekNodeId,
      pairStart,pairSlots,spreadKey,wrappers,pages,pagesWrap,allowPendingPrShell};
  };
  const syncNativeCandidateSpread = () => {
    const spread=frozenLayoutForCurrentDocument();
    const key=spread ? spread.spreadKey : null;
    if (key !== nativeCandidateSpreadKey) {
      nativeCandidates.clear();
      nativeCandidateSpreadKey=key;
    }
    return spread;
  };
  document.addEventListener('input', event => {
    if (event.target instanceof HTMLInputElement && event.target.type === 'range') syncNativeCandidateSpread();
  }, true);
  document.addEventListener('change', event => {
    if (event.target instanceof HTMLInputElement && event.target.type === 'range') syncNativeCandidateSpread();
  }, true);
  const drawEligibility = canvas => {
    if (!(canvas instanceof HTMLCanvasElement)) return null;
    const spread=syncNativeCandidateSpread();
    if (!spread) return null;
    const slot=slotOf(canvas);
    if (slot === null || !spread.pairSlots.includes(slot) || spread.layout.roles[slot] !== 'body') return null;
    const wrapper=spread.wrappers[slot];
    const canvases=[...wrapper.querySelectorAll('canvas')];
    if (canvases.length !== 1 || canvases[0] !== canvas) return null;
    return {spread,slot,wrapper,targetRectBefore:rectOf(canvas),wrapperRectBefore:rectOf(wrapper)};
  };
  const rectsHaveSameSize = (left,right) => left && right &&
    Math.abs(left.width-right.width)<=0.001 && Math.abs(left.height-right.height)<=0.001 &&
    left.width>0 && left.height>0;
  const sameTranslation = (fromTarget,toTarget,fromWrapper,toWrapper) => {
    const values=[fromTarget,toTarget,fromWrapper,toWrapper];
    if (values.some(value => !value || ![value.x,value.y,value.width,value.height].every(Number.isFinite))) return false;
    if (!rectsHaveSameSize(fromTarget,toTarget) || !rectsHaveSameSize(fromWrapper,toWrapper)) return false;
    const targetDx=toTarget.x-fromTarget.x, targetDy=toTarget.y-fromTarget.y;
    const wrapperDx=toWrapper.x-fromWrapper.x, wrapperDy=toWrapper.y-fromWrapper.y;
    return Math.abs(targetDx-wrapperDx)<=0.001 && Math.abs(targetDy-wrapperDy)<=0.001;
  };
  const activeBodyCanvas = canvas => {
    const slot = slotOf(canvas);
    if (slot === null) return null;
    const wrapper = canvas.closest('.-cv-page');
    const pagesWrap = document.querySelector('.-cv-pages-wrap');
    if (!wrapper || !pagesWrap) return null;
    // Visibility and loaded/rendered classes are required only when a frozen
    // target is materialized. Draw-time acquisition is keyed by the public
    // seek's logical spread and structural wrapper role instead.
    const rect = wrapper.getBoundingClientRect();
    const viewport = pagesWrap.getBoundingClientRect();
    if (rect.width <= 0 || rect.height <= 0 || viewport.width <= 0 || viewport.height <= 0) return null;
    const width = Math.max(0, Math.min(rect.right, viewport.right) - Math.max(rect.left, viewport.left));
    const height = Math.max(0, Math.min(rect.bottom, viewport.bottom) - Math.max(rect.top, viewport.top));
    if (width * height / (rect.width * rect.height) < 0.98) return null;
    const style = getComputedStyle(wrapper);
    if (style.display === 'none' || style.visibility === 'hidden' || Number(style.opacity || '1') <= 0) return null;
    return slot;
  };
  const contextAttributes = context => {
    try { return context && context.getContextAttributes ? context.getContextAttributes() : null; }
    catch (_) { return null; }
  };
  const contextState = context => {
    const attributes = contextAttributes(context);
    let transform = null;
    try {
      const value = context.getTransform();
      transform = [value.a,value.b,value.c,value.d,value.e,value.f].map(Number);
    } catch (_) {}
    return {
      transform,
      globalAlpha:Number(context.globalAlpha),
      globalCompositeOperation:String(context.globalCompositeOperation),
      filter:typeof context.filter === 'string' ? context.filter : null,
      imageSmoothingEnabled:Boolean(context.imageSmoothingEnabled),
      imageSmoothingQuality:context.imageSmoothingQuality || null,
      shadowColor:context.shadowColor || null,
      shadowBlur:Number(context.shadowBlur || 0),
      shadowOffsetX:Number(context.shadowOffsetX || 0),
      shadowOffsetY:Number(context.shadowOffsetY || 0),
      attributes:attributes && {
        alpha:attributes.alpha,
        colorSpace:attributes.colorSpace,
        colorType:attributes.colorType || null,
        desynchronized:attributes.desynchronized,
        willReadFrequently:attributes.willReadFrequently
      }
    };
  };
  const sourceType = source => {
    if (source instanceof HTMLCanvasElement) return 'HTMLCanvasElement';
    if (source instanceof HTMLImageElement) return 'HTMLImageElement';
    if (typeof OffscreenCanvas !== 'undefined' && source instanceof OffscreenCanvas) return 'OffscreenCanvas';
    if (typeof ImageBitmap !== 'undefined' && source instanceof ImageBitmap) return 'ImageBitmap';
    return source && source.constructor ? String(source.constructor.name) : 'unknown';
  };
  const recordHistory = (canvas, kind, args, context) => {
    if (!(canvas instanceof HTMLCanvasElement)) return;
    let history = histories.get(canvas) || [];
    if (history.length >= MAX_HISTORY) {
      historyOverflow.add(canvas);
      return;
    }
    const source = kind === 'drawImage' ? args[0] : null;
    const sourceWidth = source ? Number(source.naturalWidth || source.videoWidth || source.width || 0) : null;
    const sourceHeight = source ? Number(source.naturalHeight || source.videoHeight || source.height || 0) : null;
    history = history.concat([{
      kind,
      args:kind === 'drawImage' ? args.slice(1).map(value => Number(value)) : [],
      sourceType:source ? sourceType(source) : null,
      sourceDimensions:source ? [sourceWidth,sourceHeight] : null,
      targetDimensions:[canvas.width,canvas.height],
      context:contextState(context),
      clipCountBefore:clipCounts.get(canvas)||0
    }]);
    histories.set(canvas, history);
  };
  const noteDraw = canvas => {
    if (!(canvas instanceof HTMLCanvasElement)) return;
    epochs.set(canvas, epoch(canvas) + 1);
    totalDraws++;
  };
  const noteReset = canvas => {
    if (!(canvas instanceof HTMLCanvasElement)) return;
    epochs.set(canvas, epoch(canvas) + 1);
    generations.set(canvas, generation(canvas) + 1);
    histories.set(canvas, []);
    historyOverflow.delete(canvas);
    clipCounts.set(canvas, 0);
    nativeCandidates.delete(canvas);
    totalDraws++;
  };
  const proto = window.CanvasRenderingContext2D && CanvasRenderingContext2D.prototype;
  const canvasProto = window.HTMLCanvasElement && HTMLCanvasElement.prototype;
  if (canvasProto) {
    for (const name of ['width', 'height']) {
      const descriptor = Object.getOwnPropertyDescriptor(canvasProto, name);
      if (!descriptor || typeof descriptor.get !== 'function' ||
          typeof descriptor.set !== 'function' || !descriptor.configurable) continue;
      try {
        Object.defineProperty(canvasProto, name, {
          ...descriptor,
          get: function() { return descriptor.get.call(this); },
          set: function(value) {
            const result = descriptor.set.call(this, value);
            noteReset(this);
            return result;
          }
        });
      } catch (_) { /* preserve native descriptor when wrapping is unsupported */ }
    }
  }
  if (proto) {
    for (const name of ['drawImage','putImageData','clearRect','fillRect','strokeRect',
                        'fill','stroke','fillText','strokeText']) {
      const descriptor = Object.getOwnPropertyDescriptor(proto, name);
      const original = descriptor && descriptor.value;
      if (typeof original !== 'function' || !descriptor.configurable) continue;
      try {
        Object.defineProperty(proto, name, { ...descriptor,
          value: function(...args) {
            const canvas = this.canvas;
            const canvasSlot = slotOf(canvas);
            const targetNodeId = nodeId(canvas);
            const targetEpochBefore = epoch(canvas);
            const targetGenerationBefore = generation(canvas);
            if (canvasSlot !== null || nativeCandidates.has(canvas)) nativeCandidates.delete(canvas);
            const eligibility = name === 'drawImage' ? drawEligibility(canvas) : null;
            const candidateEligible = eligibility !== null;
            let candidate = null;
            if (candidateEligible) {
              try {
                const source = args[0];
                const sourceWidth = Number(source && (source.naturalWidth || source.videoWidth || source.width) || 0);
                const sourceHeight = Number(source && (source.naturalHeight || source.videoHeight || source.height) || 0);
                const sourceTypeName = sourceType(source);
                const sourceCanvasId = source instanceof HTMLCanvasElement ? nodeId(source) : null;
                const sourceGeneration = source instanceof HTMLCanvasElement ? generation(source) : null;
                const sourceEpoch = source instanceof HTMLCanvasElement ? epoch(source) : null;
                const sourceHistory = source instanceof HTMLCanvasElement ? histories.get(source) || [] : [];
                const sourceHistoryOverflown = source instanceof HTMLCanvasElement && historyOverflow.has(source);
                const sourceContext = source instanceof HTMLCanvasElement ? source.getContext('2d') : null;
                const sourceAttributes = contextAttributes(sourceContext);
                const targetAttributes = contextAttributes(this);
                const observedNativeColor = attributes => attributes && attributes.colorSpace === 'srgb' &&
                  attributes.colorType === 'unorm8';
                const targetColorSafe = observedNativeColor(targetAttributes);
                const sourceImage = sourceContext && targetColorSafe && observedNativeColor(sourceAttributes) &&
                  sourceWidth > 0 && sourceHeight > 0 && sourceWidth * sourceHeight <= MAX_NATIVE_PIXELS
                  ? sourceContext.getImageData(0,0,sourceWidth,sourceHeight)
                  : null;
                const data = sourceImage && sourceImage.data instanceof Uint8ClampedArray
                  ? sourceImage.data : null;
                if (data && targetColorSafe) candidate = {
                  slot:eligibility.slot,
                  targetCanvas:canvas,
                  targetNodeId,
                  rootNodeId:eligibility.spread.layout.rootNodeId,
                  pagesWrapNodeId:eligibility.spread.layout.pagesWrapNodeId,
                  pagesRootNodeId:eligibility.spread.layout.pagesRootNodeId,
                  wrapperNodeId:nodeId(eligibility.wrapper),
                  layout:eligibility.spread.layout,
                  pairSlots:eligibility.spread.pairSlots.slice(),
                  layoutKey:eligibility.spread.layoutKey,
                  spreadKey:eligibility.spread.spreadKey,
                  seekNodeId:eligibility.spread.seekNodeId,
                  seekValue:eligibility.spread.seekValue,
                  pairStart:eligibility.spread.pairStart,
                  targetRectBefore:eligibility.targetRectBefore,
                  wrapperRectBefore:eligibility.wrapperRectBefore,
                  targetGenerationBefore,
                  targetEpochBefore,
                  targetWidth:canvas.width,
                  targetHeight:canvas.height,
                  sourceType:sourceTypeName,
                  sourceCanvasId,
                  sourceGeneration,
                  sourceEpoch,
                  sourceWidth,
                  sourceHeight,
                  sourceColorSpace:sourceAttributes.colorSpace,
                  sourceColorType:sourceAttributes.colorType,
                  targetColorSpace:targetAttributes.colorSpace,
                  targetColorType:targetAttributes.colorType,
                  sourcePixels:new Uint8ClampedArray(data),
                  sourceHistory:sourceHistory.slice(0,MAX_HISTORY),
                  sourceHistoryOverflown,
                  drawArguments:args.slice(1).map(value => Number(value)),
                  context:contextState(this),
                  clipCountBefore:clipCounts.get(canvas)||0
                };
              } catch (_) { candidate = null; }
            }
            const result = original.apply(this, args);
            noteDraw(canvas);
            recordHistory(canvas,name,args,this);
            if (candidate) {
              candidate.targetGenerationAfter = generation(canvas);
              candidate.targetEpochAfter = epoch(canvas);
              candidate.targetRectAfter = rectOf(canvas);
              candidate.wrapperRectAfter = rectOf(eligibility.wrapper);
              const spreadAfter = syncNativeCandidateSpread();
              const drawStayedOnBoundSpread = spreadAfter &&
                spreadAfter.spreadKey === candidate.spreadKey &&
                spreadAfter.layoutKey === candidate.layoutKey &&
                spreadAfter.layout.wrapperNodeIds[candidate.slot] === candidate.wrapperNodeId &&
                nodeId(canvas) === candidate.targetNodeId &&
                targetGenerationBefore === candidate.targetGenerationBefore &&
                candidate.targetGenerationAfter === candidate.targetGenerationBefore &&
                candidate.targetEpochAfter === candidate.targetEpochBefore + 1 &&
                sameTranslation(candidate.targetRectBefore,candidate.targetRectAfter,
                  candidate.wrapperRectBefore,candidate.wrapperRectAfter);
              if (!drawStayedOnBoundSpread) candidate = null;
            }
            if (candidate) {
              for (const [existingCanvas,existing] of nativeCandidates.entries()) {
                if (existing.slot === candidate.slot && existingCanvas !== canvas)
                  nativeCandidates.delete(existingCanvas);
              }
              if (nativeCandidates.size < MAX_NATIVE_TARGETS || nativeCandidates.has(canvas))
                nativeCandidates.set(canvas,candidate);
            }
            return result;
          }
        });
      } catch (_) { /* unsupported prototype properties stay unobserved */ }
    }
    const clipDescriptor = Object.getOwnPropertyDescriptor(proto,'clip');
    const originalClip = clipDescriptor && clipDescriptor.value;
    if (typeof originalClip === 'function' && clipDescriptor.configurable) {
      try {
        Object.defineProperty(proto,'clip',{...clipDescriptor,value:function(...args) {
          const result = originalClip.apply(this,args);
          const canvas = this.canvas;
          if (canvas instanceof HTMLCanvasElement) clipCounts.set(canvas,(clipCounts.get(canvas)||0)+1);
          return result;
        }});
      } catch (_) {}
    }
    const resetDescriptor = Object.getOwnPropertyDescriptor(proto, 'reset');
    const originalReset = resetDescriptor && resetDescriptor.value;
    if (typeof originalReset === 'function' && resetDescriptor.configurable) {
      try {
        Object.defineProperty(proto, 'reset', {
          ...resetDescriptor,
          value: function(...args) {
            const canvas = this.canvas;
            const result = originalReset.apply(this, args);
            noteReset(canvas);
            return result;
          }
        });
      } catch (_) { /* preserve native reset when wrapping is unsupported */ }
    }
  }
  const sameBytes = (left,right) => {
    if (!left || !right || left.length !== right.length) return false;
    for (let index=0; index<left.length; index++) if (left[index] !== right[index]) return false;
    return true;
  };
  const canvasPixels = canvas => {
    try {
      const context = canvas.getContext('2d');
      const attributes = contextAttributes(context);
      if (!context || !attributes || attributes.colorSpace !== 'srgb' || attributes.colorType !== 'unorm8')
        return null;
      const image = context.getImageData(0,0,canvas.width,canvas.height);
      if (!(image.data instanceof Uint8ClampedArray)) return null;
      return {pixels:new Uint8ClampedArray(image.data),colorSpace:attributes.colorSpace,colorType:attributes.colorType};
    } catch (_) { return null; }
  };
  const dataUrl = async canvas => {
    try {
      const blob = await canvas.convertToBlob({type:'image/png'});
      const bytes = new Uint8Array(await blob.arrayBuffer());
      let binary = '';
      for (let offset=0; offset<bytes.length; offset+=0x8000)
        binary += String.fromCharCode(...bytes.subarray(offset,Math.min(offset+0x8000,bytes.length)));
      return `data:image/png;base64,${btoa(binary)}`;
    } catch (_) { return null; }
  };
  const documentIdentity = () => {
    const canonical = [...document.querySelectorAll('link[rel="canonical"]')].map(node => node.href);
    const episodeId = location.pathname.match(/^\/episodes\/([0-9a-f]{13})\/?$/)?.[1] || null;
    const headers = [...document.querySelectorAll('#xHeader')];
    const workLinks = headers.length === 1 ? [...headers[0].querySelectorAll('a.ep-h-main-h-series')] : [];
    let workPath = null;
    if (workLinks.length === 1) {
      try {
        const url = new URL(workLinks[0].getAttribute('href') || '',location.href);
        if (url.origin === 'https://heros-web.com' && !url.search && !url.hash) workPath = url.pathname;
      } catch (_) {}
    }
    return {url:location.href,canonical,episodeId,workPath};
  };
  const readSeek = () => [...document.querySelectorAll('input[type="range"]')].map(node => ({
    nodeId:nodeId(node),min:node.min,max:node.max,step:node.step,value:node.value,disabled:node.disabled
  }));
  const stateForTarget = (slot,target) => {
    const pages = document.querySelector('.-cv-pages');
    const wrapper = pages && pages.children[slot];
    const seek = readSeek();
    return {
      slot:wrapper && wrapper.contains(target) ? slot : null,
      wrapperNodeId:wrapper ? nodeId(wrapper) : null,
      targetRect:rectOf(target),wrapperRect:wrapper ? rectOf(wrapper) : null,
      nodeId:nodeId(target),width:target.width,height:target.height,
      epoch:epoch(target),generation:generation(target),
      seek,classes:wrapper ? (wrapper.getAttribute('class')||'').split(/\s+/).filter(Boolean).sort() : []
    };
  };
  const sameLayout = (left,right) => {
    if (!left || !right) return false;
    const scalarKeys=['episodeId','workPath','url','rootNodeId','pagesWrapNodeId','pagesRootNodeId',
      'ciSlot','goodSlot','lastSlot','seekNodeId','seekMin','seekMax','seekStep'];
    const arrayKeys=['canonical','wrapperNodeIds','roles','bodySlots','prSlots','rootStructuralModes'];
    return scalarKeys.every(key => left[key] === right[key]) &&
      arrayKeys.every(key => JSON.stringify(left[key]) === JSON.stringify(right[key]));
  };
  const sameCandidateLayout = (candidate,current,candidateSeekValue,candidatePairStart) => {
    if (sameLayout(candidate,current)) return true;
    if (!candidate || !current || !sameLayout(
      {...candidate,rootStructuralModes:current.rootStructuralModes},current)) return false;
    const candidateModes=candidate.rootStructuralModes || [];
    const currentModes=current.rootStructuralModes || [];
    return candidateSeekValue === candidate.seekMax && candidatePairStart === 0 &&
      current.seekMax === candidate.seekMax &&
      !candidateModes.includes('mode-has-pr') && currentModes.includes('mode-has-pr') &&
      candidateModes.length+1===currentModes.length &&
      candidateModes.every(mode => currentModes.includes(mode));
  };
  const sameRect = (left,right) => left && right &&
    ['x','y','width','height'].every(key => Number.isFinite(left[key]) && Number.isFinite(right[key]) &&
      Math.abs(left[key]-right[key])<=0.001);
  const createOffscreen = (width,height,attributes) => {
    if (typeof OffscreenCanvas === 'undefined') return null;
    const canvas = new OffscreenCanvas(width,height);
    const context = canvas.getContext('2d',attributes);
    return context ? {canvas,context} : null;
  };
  const materializeNativeTargets = async request => {
    if (nativeMaterializationInFlight)
      return {status:'unsupported',reason:'native_materialization_busy'};
    nativeMaterializationInFlight = true;
    try {
    const beforeIdentity = documentIdentity();
    const beforeSeek = readSeek();
    const beforeDraws = totalDraws;
    const currentSpread = syncNativeCandidateSpread();
    if (!request || beforeIdentity.url !== request.expectedUrl || beforeIdentity.episodeId !== request.episodeId ||
        beforeIdentity.workPath !== `/series/${request.workId}` ||
        beforeIdentity.canonical.length !== 1 || beforeIdentity.canonical[0] !== request.expectedUrl)
      return {status:'identity_drift'};
    if (!Array.isArray(request.targets) || request.targets.length < 1 || request.targets.length > 2 ||
        beforeSeek.length !== 1 || beforeSeek[0].nodeId !== request.seekNodeId ||
        beforeSeek[0].value !== String(request.seekValue) || !currentSpread ||
        currentSpread.seekNodeId !== request.seekNodeId || currentSpread.seekValue !== request.seekValue ||
        !sameLayout(currentSpread.layout,request.layout))
      return {status:'target_drift'};
    const pages = document.querySelector('.-cv-pages');
    const pagesWrap = document.querySelector('.-cv-pages-wrap');
    if (!pages || !pagesWrap) return {status:'unsupported'};
    const pending = [];
    for (const expected of request.targets) {
      const wrapper = pages.children[expected.slot];
      const target = wrapper && wrapper.querySelector('canvas');
      if (!wrapper || !target || nodeId(target) !== expected.nodeId || slotOf(target) !== expected.slot)
        return {status:'target_drift'};
      if (!currentSpread.pairSlots.includes(expected.slot) ||
          currentSpread.layout.roles[expected.slot] !== 'body' ||
          currentSpread.layout.wrapperNodeIds[expected.slot] !== nodeId(wrapper) ||
          expected.wrapperNodeId !== nodeId(wrapper) ||
          expected.rootNodeId !== currentSpread.layout.rootNodeId ||
          expected.pagesWrapNodeId !== currentSpread.layout.pagesWrapNodeId ||
          expected.pagesRootNodeId !== currentSpread.layout.pagesRootNodeId ||
          expected.seekNodeId !== request.seekNodeId || expected.seekValue !== request.seekValue ||
          expected.pairStart !== currentSpread.pairStart ||
          JSON.stringify(expected.pairSlots) !== JSON.stringify(currentSpread.pairSlots) ||
          JSON.stringify(expected.rootStructuralModes) !== JSON.stringify(request.layout.rootStructuralModes))
        return {status:'target_drift'};
      const wrapperClass = new Set((wrapper.getAttribute('class')||'').split(/\s+/).filter(Boolean));
      if (!wrapperClass.has('mode-loaded') || !wrapperClass.has('mode-rendered'))
        return {status:'unsupported'};
      const activeSlot = activeBodyCanvas(target);
      const state = stateForTarget(expected.slot,target);
      if (activeSlot !== expected.slot || state.width !== expected.width || state.height !== expected.height ||
          state.epoch !== expected.drawEpoch || state.generation !== expected.generation ||
          expected.seekValue !== request.seekValue)
        return {status:'target_drift'};
      const targetPixelState = canvasPixels(target);
      if (!targetPixelState) return {status:'unsupported',reason:'target_color_format_unsupported'};
      const pixels = targetPixelState.pixels;
      const observedCandidate = nativeCandidates.get(target);
      const candidate = observedCandidate && observedCandidate.spreadKey === currentSpread.spreadKey &&
        observedCandidate.layoutKey === currentSpread.layoutKey &&
        sameCandidateLayout(observedCandidate.layout,currentSpread.layout,
          observedCandidate.seekValue,observedCandidate.pairStart) &&
        observedCandidate.seekNodeId === request.seekNodeId &&
        observedCandidate.seekValue === request.seekValue &&
        observedCandidate.rootNodeId === currentSpread.layout.rootNodeId &&
        observedCandidate.pagesWrapNodeId === currentSpread.layout.pagesWrapNodeId &&
        observedCandidate.pagesRootNodeId === currentSpread.layout.pagesRootNodeId &&
        observedCandidate.wrapperNodeId === nodeId(wrapper) &&
        observedCandidate.seekNodeId === expected.seekNodeId &&
        observedCandidate.seekValue === expected.seekValue &&
        observedCandidate.pairStart === expected.pairStart &&
        JSON.stringify(observedCandidate.pairSlots) === JSON.stringify(expected.pairSlots) &&
        sameCandidateLayout(observedCandidate.layout,request.layout,
          observedCandidate.seekValue,observedCandidate.pairStart) ? observedCandidate : null;
      const sameCandidateTarget = candidate && candidate.targetNodeId === expected.nodeId &&
        candidate.targetEpochAfter === expected.drawEpoch && candidate.targetGenerationAfter === expected.generation &&
        candidate.slot === expected.slot && candidate.targetWidth === expected.width && candidate.targetHeight === expected.height;
      const supportedSourceDimensions = candidate &&
        ((candidate.sourceWidth === 1440 && candidate.sourceHeight === 2048) ||
         (candidate.sourceWidth === 844 && candidate.sourceHeight === 1200));
      if (!sameCandidateTarget || !supportedSourceDimensions || candidate.sourceHistoryOverflown ||
          candidate.sourceType !== 'HTMLCanvasElement' || candidate.sourcePixels.length !== candidate.sourceWidth*candidate.sourceHeight*4 ||
          !sameTranslation(candidate.targetRectBefore,candidate.targetRectAfter,
            candidate.wrapperRectBefore,candidate.wrapperRectAfter) ||
          !sameTranslation(candidate.targetRectAfter,state.targetRect,
            candidate.wrapperRectAfter,state.wrapperRect)) {
        pending.push({expected,target,state,pixels,candidate:null});
        continue;
      }
      const sourceHistory = candidate.sourceHistory;
      if (sourceHistory.length !== 16 || sourceHistory.some(item => item.kind !== 'drawImage')) {
        pending.push({expected,target,state,pixels,candidate:null});
        continue;
      }
      const sourceCreated = createOffscreen(candidate.sourceWidth,candidate.sourceHeight,{willReadFrequently:true});
      if (!sourceCreated) {
        pending.push({expected,target,state,pixels,candidate:null});
        continue;
      }
      sourceCreated.context.putImageData(
        new ImageData(new Uint8ClampedArray(candidate.sourcePixels),candidate.sourceWidth,candidate.sourceHeight),0,0
      );
      const copiedSource = canvasPixels(sourceCreated.canvas);
      if (!copiedSource || !sameBytes(copiedSource.pixels,candidate.sourcePixels)) {
        pending.push({expected,target,state,pixels,candidate:null});
        continue;
      }
      const sourcePng = await dataUrl(sourceCreated.canvas);
      const args = candidate.drawArguments;
      const contextState = candidate.context;
      const safeDraw = expected.width === 934 && expected.height === 1329 &&
        Array.isArray(args) && args.length === 8 &&
        args[0] === 0 && args[1] === 0 && args[2] === candidate.sourceWidth && args[3] === candidate.sourceHeight &&
        args[4] === 0 && args[5] === 0 && args[6] === 934.5 && args[7] === 1329 &&
        contextState && contextState.transform && contextState.transform.join(',') === '1,0,0,1,0,0' &&
        contextState.attributes && contextState.attributes.colorSpace === 'srgb' &&
        contextState.attributes.colorType === 'unorm8' &&
        contextState.globalAlpha === 1 && contextState.globalCompositeOperation === 'source-over' &&
        contextState.filter === 'none' && contextState.shadowBlur === 0 &&
        contextState.shadowOffsetX === 0 && contextState.shadowOffsetY === 0 && candidate.clipCountBefore === 0;
      if (!sourcePng || !safeDraw) {
        pending.push({expected,target,state,pixels,candidate:null});
        continue;
      }
      const replayCreated = createOffscreen(expected.width,expected.height,contextState.attributes || undefined);
      if (!replayCreated) {
        pending.push({expected,target,state,pixels,candidate:null});
        continue;
      }
      replayCreated.context.setTransform(...contextState.transform);
      replayCreated.context.globalAlpha = contextState.globalAlpha;
      replayCreated.context.globalCompositeOperation = contextState.globalCompositeOperation;
      if (contextState.filter && 'filter' in replayCreated.context) replayCreated.context.filter = contextState.filter;
      replayCreated.context.imageSmoothingEnabled = contextState.imageSmoothingEnabled;
      if (contextState.imageSmoothingQuality && 'imageSmoothingQuality' in replayCreated.context)
        replayCreated.context.imageSmoothingQuality = contextState.imageSmoothingQuality;
      replayCreated.context.shadowColor = contextState.shadowColor;
      replayCreated.context.shadowBlur = contextState.shadowBlur;
      replayCreated.context.shadowOffsetX = contextState.shadowOffsetX;
      replayCreated.context.shadowOffsetY = contextState.shadowOffsetY;
      replayCreated.context.drawImage(sourceCreated.canvas,...args);
      const replayPng = await dataUrl(replayCreated.canvas);
      const replayPixelState = canvasPixels(replayCreated.canvas);
      if (!replayPixelState) {
        pending.push({expected,target,state,pixels,candidate:null});
        continue;
      }
      const replayMatchesTarget = sameBytes(replayPixelState.pixels,pixels);
      const tileHistory = sourceHistory.map((item,ordinal) => ({
        ordinal,kind:item.kind,sourceType:item.sourceType,args:item.args,sourceDimensions:item.sourceDimensions,
        targetDimensions:item.targetDimensions,context:item.context,clipCountBefore:item.clipCountBefore
      }));
      pending.push({expected,target,state,pixels,candidate,sourcePng,replayPng,replayMatchesTarget,tileHistory});
    }
      const records = pending.map(item => {
      const state = item.state;
      const candidate = item.candidate;
        if (!candidate || !item.sourcePng || !item.replayPng) return {
          slot:item.expected.slot,supported:false,reason:!candidate?'source_candidate_unavailable':'snapshot_or_replay_unavailable'
        };
        if (!item.replayMatchesTarget) return {
          slot:item.expected.slot,supported:false,reason:'source_replay_mismatch'
        };
      return {
        slot:item.expected.slot,
        supported:true,
        width:candidate.sourceWidth,
        height:candidate.sourceHeight,
        sourcePng:item.sourcePng,
        proof:{
          targetNodeId:state.nodeId,
          targetSlotBefore:state.slot,
          targetEpochBefore:state.epoch,
          targetGenerationBefore:state.generation,
          targetSlotAfter:state.slot,
          drawTargetRectBefore:candidate.targetRectBefore,
          drawTargetRectAfter:candidate.targetRectAfter,
          drawWrapperRectBefore:candidate.wrapperRectBefore,
          drawWrapperRectAfter:candidate.wrapperRectAfter,
          materializedTargetRect:state.targetRect,
          materializedWrapperRect:state.wrapperRect,
          drawToCaptureCommonTranslation:true,
          targetEpochAfter:state.epoch,
          targetGenerationAfter:state.generation,
          candidateTargetEpochAfterDraw:candidate.targetEpochAfter,
          candidateTargetGenerationAfterDraw:candidate.targetGenerationAfter,
          drawRootNodeId:candidate.rootNodeId,
          drawPagesWrapNodeId:candidate.pagesWrapNodeId,
          drawPagesRootNodeId:candidate.pagesRootNodeId,
          drawWrapperNodeId:candidate.wrapperNodeId,
          drawSeekNodeId:candidate.seekNodeId,
          drawSeekValue:candidate.seekValue,
          drawSeekMax:candidate.layout.seekMax,
          drawPairStart:candidate.pairStart,
          drawPairSlots:candidate.pairSlots,
          drawRootStructuralModes:candidate.layout.rootStructuralModes,
          drawTargetEpochBefore:candidate.targetEpochBefore,
          drawTargetEpochAfter:candidate.targetEpochAfter,
          drawTargetGenerationBefore:candidate.targetGenerationBefore,
          drawTargetGenerationAfter:candidate.targetGenerationAfter,
          targetPixelsStable:(() => {
            const current = canvasPixels(item.target);
            return current !== null && sameBytes(item.pixels,current.pixels);
          })(),
          sourceReplayMatchesTarget:item.replayMatchesTarget,
          sourceCanvasNodeId:candidate.sourceCanvasId,
          sourceGenerationAtDraw:candidate.sourceGeneration,
          sourceEpochAtDraw:candidate.sourceEpoch,
          sourceType:candidate.sourceType,
          sourceDimensions:[candidate.sourceWidth,candidate.sourceHeight],
          sourceColorSpace:candidate.sourceColorSpace,
          sourceColorType:candidate.sourceColorType,
          targetColorSpace:candidate.targetColorSpace,
          targetColorType:candidate.targetColorType,
          drawArguments:candidate.drawArguments,
          context:candidate.context,
          clipCountBefore:candidate.clipCountBefore,
          sourceHistoryComplete:!candidate.sourceHistoryOverflown && candidate.sourceHistory.length===16,
          sourceTileDrawCount:candidate.sourceHistory.length,
          sourceTileHistory:item.tileHistory,
          observerDrawsBefore:beforeDraws,
          observerDrawsAfter:totalDraws
        },
        replayPng:item.replayPng,
        targetNodeIdAfter:nodeId(item.target),
        targetEpochAfter:epoch(item.target),
        targetGenerationAfter:generation(item.target),
        targetSlotAfter:slotOf(item.target)
      };
    });
    const afterIdentity = documentIdentity();
    const afterSeek = readSeek();
    const afterSpread = syncNativeCandidateSpread();
    if (JSON.stringify(beforeIdentity)!==JSON.stringify(afterIdentity)) return {status:'identity_drift'};
    if (JSON.stringify(beforeSeek)!==JSON.stringify(afterSeek)) return {status:'target_drift'};
    if (!afterSpread || afterSpread.spreadKey !== currentSpread.spreadKey ||
        !sameLayout(afterSpread.layout,request.layout)) return {status:'target_drift'};
    for (const item of pending) {
      const afterState = stateForTarget(item.expected.slot,item.target);
      const afterPixels = canvasPixels(item.target);
      if (afterState.nodeId!==item.expected.nodeId || afterState.slot!==item.expected.slot ||
          afterState.epoch!==item.expected.drawEpoch || afterState.generation!==item.expected.generation ||
          !afterPixels || !sameBytes(item.pixels,afterPixels.pixels) ||
          !sameRect(item.state.targetRect,afterState.targetRect) ||
          !sameRect(item.state.wrapperRect,afterState.wrapperRect) ||
          activeBodyCanvas(item.target)!==item.expected.slot) return {status:'target_drift'};
    }
    for (const item of pending) {
      if (item.candidate && nativeCandidates.get(item.target) === item.candidate)
        nativeCandidates.delete(item.target);
    }
    return {
      status:'ok',documentBefore:beforeIdentity,documentAfter:afterIdentity,
      seekBefore:beforeSeek,seekAfter:afterSeek,
      observerStable:beforeDraws===totalDraws,
      observerDrawsChanged:beforeDraws!==totalDraws,
      observerDrawsBefore:beforeDraws,observerDrawsAfter:totalDraws,records
    };
    } finally {
      nativeMaterializationInFlight = false;
    }
  };
  const releaseNativeTargets = slots => {
    if (!Array.isArray(slots)) return;
    for (const [canvas,candidate] of nativeCandidates.entries()) {
      const expected = slots.find(item => item && item.slot === candidate.slot);
      if (expected && candidate.targetNodeId === expected.nodeId &&
          candidate.targetEpochAfter === expected.drawEpoch &&
          candidate.targetGenerationAfter === expected.generation &&
          nativeCandidates.get(canvas) === candidate) nativeCandidates.delete(canvas);
    }
  };
  window.__hwebCaptureObserver = {
    nodeId,
    epoch,
    generation,
    currentLayout:() => {
      const spread=syncNativeCandidateSpread();
      return spread ? spread.layout : null;
    },
    get totalDraws() { return totalDraws; },
    materializeNativeTargets,
    releaseNativeTargets
  };
})();"""

_EPISODE_ENTRY_SCRIPT = r"""() => {
  const cleanPath = raw => {
    try {
      const url = new URL(raw || '', location.href);
      if (url.origin !== 'https://heros-web.com' || url.search || url.hash) return null;
      return url.pathname;
    } catch { return null; }
  };
  const headers = [...document.querySelectorAll('#xHeader')];
  const links = headers.length === 1
    ? [...headers[0].querySelectorAll('a.ep-h-main-h-series')] : [];
  const canonical = [...document.querySelectorAll('link[rel="canonical"]')].map(node => node.href);
  const visible = node => {
    const style = getComputedStyle(node), rect = node.getBoundingClientRect();
    return style.display !== 'none' && style.visibility !== 'hidden' &&
      Number(style.opacity || '1') > 0 && rect.width > 0 && rect.height > 0;
  };
  const chargeGates = [...document.querySelectorAll('.ep-main-content.mode-charge')].filter(visible);
  const visibleLoginActions = [...document.querySelectorAll('a,button')].filter(visible).filter(node => {
    const text = (node.innerText || '').replace(/\s+/g, ' ').trim();
    const path = cleanPath(node.getAttribute('href')) || '';
    return path === '/auth/signin' || path === '/auth/signup' ||
      text === 'ログインして読む' || text === '無料登録して読む';
  });
  const episodeId = location.pathname.match(/^\/episodes\/([0-9a-f]{13})\/?$/)?.[1] || null;
  return {
    url: location.href,
    episodeId,
    canonical,
    headerCount: headers.length,
    workLinkCount: links.length,
    workPath: links.length === 1 ? cleanPath(links[0].getAttribute('href')) : null,
    chargeGateCount: chargeGates.length,
    visibleLoginActionCount: visibleLoginActions.length,
    viewerFrameCount: document.querySelectorAll('.-cv iframe, .-cv-pages iframe').length
  };
}"""

_VIEWER_SNAPSHOT_SCRIPT = r"""() => {
  const observer = window.__hwebCaptureObserver;
  const classes = node => (node.getAttribute('class') || '').split(/\s+/).filter(Boolean).sort();
  const rect = node => {
    const value = node.getBoundingClientRect();
    return {x:value.x, y:value.y, width:value.width, height:value.height};
  };
  const visibleStyle = node => {
    const value = getComputedStyle(node);
    return {display:value.display, visibility:value.visibility, opacity:value.opacity};
  };
  const roots = [...document.querySelectorAll('.-cv')];
  const wraps = [...document.querySelectorAll('.-cv-pages-wrap')];
  const pagesRoots = [...document.querySelectorAll('.-cv-pages')];
  const root = roots.length === 1 ? roots[0] : null;
  const pagesWrap = wraps.length === 1 ? wraps[0] : null;
  const pagesRoot = pagesRoots.length === 1 ? pagesRoots[0] : null;
  const viewport = pagesWrap;
  const viewportRect = viewport ? rect(viewport) : null;
  const intersectRatio = value => {
    if (!viewportRect || value.width <= 0 || value.height <= 0) return 0;
    const left = Math.max(value.x, viewportRect.x);
    const top = Math.max(value.y, viewportRect.y);
    const right = Math.min(value.x + value.width, viewportRect.x + viewportRect.width);
    const bottom = Math.min(value.y + value.height, viewportRect.y + viewportRect.height);
    return Math.max(0,right-left) * Math.max(0,bottom-top) / (value.width * value.height);
  };
  const wrappers = pagesRoot ? [...pagesRoot.children] : [];
  const readCanvas = canvas => ({
    nodeId: observer ? observer.nodeId(canvas) : null,
    width: canvas.width,
    height: canvas.height,
    rect: rect(canvas),
    intersection: intersectRatio(rect(canvas)),
    style: visibleStyle(canvas),
    drawEpoch: observer ? observer.epoch(canvas) : null,
    generation: observer ? observer.generation(canvas) : null
  });
  const pages = wrappers.map((node,index) => {
    const child = rect(node), children = [...node.querySelectorAll('canvas')];
    return {
      index,
      nodeId: observer ? observer.nodeId(node) : null,
      tag: node.tagName,
      classTokens: classes(node),
      rect: child,
      intersection: intersectRatio(child),
      style: visibleStyle(node),
      canvases: children.map(readCanvas)
    };
  });
  const seek = [...document.querySelectorAll('input[type="range"]')].map(node => ({
    nodeId: observer ? observer.nodeId(node) : null,
    classTokens: classes(node), min:node.min, max:node.max, step:node.step,
    value:node.value, disabled:node.disabled
  }));
  return {
    url: location.href,
    canonical: [...document.querySelectorAll('link[rel="canonical"]')].map(node => node.href),
    rootCount: roots.length,
    rootNodeId: roots.length === 1 && observer ? observer.nodeId(roots[0]) : null,
    rootClassTokens: roots.length === 1 ? classes(roots[0]) : [],
    rootRect: roots.length === 1 ? rect(roots[0]) : null,
    rootStyle: roots.length === 1 ? visibleStyle(roots[0]) : null,
    pagesWrapStyle: pagesWrap ? visibleStyle(pagesWrap) : null,
    pagesRootStyle: pagesRoot ? visibleStyle(pagesRoot) : null,
    viewerTreeValid: Boolean(root && pagesWrap && pagesRoot && root.contains(pagesWrap) && pagesWrap.contains(pagesRoot)),
    pagesWrapCount: wraps.length,
    pagesWrapNodeId: wraps.length === 1 && observer ? observer.nodeId(wraps[0]) : null,
    pagesRootCount: pagesRoots.length,
    pagesRootNodeId: pagesRoot && observer ? observer.nodeId(pagesRoot) : null,
    viewportRect,
    viewportClientWidth: viewport ? viewport.clientWidth : null,
    viewportClientHeight: viewport ? viewport.clientHeight : null,
    viewportScrollLeft: viewport ? viewport.scrollLeft : null,
    viewportScrollTop: viewport ? viewport.scrollTop : null,
    wrappers: pages,
    seek,
    viewerFrameCount: document.querySelectorAll('.-cv iframe, .-cv-pages iframe').length,
    observerTotalDraws: observer ? observer.totalDraws : null
  };
}"""


@dataclass(frozen=True, slots=True)
class _ViewerLayout:
    root_node_id: int
    pages_wrap_node_id: int
    pages_root_node_id: int
    wrapper_node_ids: tuple[int, ...]
    roles: tuple[str, ...]
    body_slots: tuple[int, ...]
    ci_slot: int
    pr_slots: tuple[int, ...]
    good_slot: int
    last_slot: int
    seek_node_id: int
    seek_min: int
    seek_max: int
    seek_step: int
    root_structural_modes: tuple[str, ...]


class HeroswebEpisodeRouteGuard:
    """Block state changes and all unapproved document navigations."""

    def __init__(self, page: Page, *, episode_id: str) -> None:
        self.page = page
        self.episode_id = episode_id
        self.expected_navigation_url: str | None = None
        self.navigation_violation: str | None = None
        self.navigation_frame_role: str | None = None
        self.unexpected_write: str | None = None
        self.blocked_telemetry: list[tuple[str, str]] = []
        self.blocked_read_completed: list[str] = []
        self.blocked_external_writes: list[str] = []
        self.main_frame_navigation_urls: list[str] = []
        self.last_main_frame_response_status: int | None = None
        self.main_frame_error_category: str | None = None

    def allow_navigation(self, url: str) -> None:
        parsed = urlsplit(url)
        if (
            parsed.scheme != "https"
            or parsed.hostname != "heros-web.com"
            or parsed.username is not None
            or parsed.password is not None
            or parsed.port not in (None, 443)
            or parsed.query
            or parsed.fragment
        ):
            raise UnknownPageStateError("HERO'S WEB refused an unsafe navigation target")
        self.expected_navigation_url = url

    async def __call__(self, route) -> None:
        request = route.request
        try:
            parsed = urlsplit(request.url)
        except ValueError:
            await route.abort()
            return
        method = request.method.upper()
        path = parsed.path
        host_path = f"{(parsed.hostname or '').lower()}{path}"
        read_completed_match = EXPECTED_READ_COMPLETED_PATH_RE.fullmatch(path)
        try:
            is_navigation = request.is_navigation_request()
        except PlaywrightError:
            self.navigation_frame_role = "unknown"
            self.navigation_violation = f"{method} {host_path} frame role unavailable"
            self.main_frame_error_category = "unexpected_navigation"
            await route.abort()
            return
        if is_navigation and method not in {"GET", "HEAD"}:
            try:
                self.navigation_frame_role = (
                    "main_frame"
                    if request.frame == self.page.main_frame
                    else "subframe"
                )
            except PlaywrightError:
                self.navigation_frame_role = "unknown"
            if self.navigation_frame_role == "subframe":
                if is_herosweb_relevant_host(request.url):
                    self.unexpected_write = host_path
                else:
                    self.blocked_external_writes.append(host_path)
                await route.abort()
                return
            self.navigation_violation = f"{method} {host_path}"
            self.main_frame_error_category = "unexpected_navigation"
            await route.abort()
            return
        if method not in {"GET", "HEAD"}:
            if parsed.hostname == "heros-web.com" and (path == "/api/missions" or (
                path == f"/api/episodes/{self.episode_id}/read"
                and EXPECTED_READ_PATH_RE.fullmatch(path) is not None
            )):
                self.blocked_telemetry.append((method, path))
            elif (
                parsed.hostname == "heros-web.com"
                and self.episode_id
                and read_completed_match is not None
                and read_completed_match.group("episode") == self.episode_id
            ):
                self.blocked_read_completed.append(path)
            elif is_herosweb_relevant_host(request.url):
                self.unexpected_write = host_path
            else:
                self.blocked_external_writes.append(host_path)
            await route.abort()
            return
        if is_navigation:
            try:
                main_frame = request.frame == self.page.main_frame
            except PlaywrightError:
                self.navigation_frame_role = "unknown"
                self.navigation_violation = f"{method} {host_path} frame role unavailable"
                self.main_frame_error_category = "unexpected_navigation"
                await route.abort()
                return
            self.navigation_frame_role = "main_frame" if main_frame else "subframe"
            if main_frame and (
                method not in {"GET", "HEAD"}
                or self.expected_navigation_url is None
                or request.url != self.expected_navigation_url
            ):
                self.navigation_violation = f"{method} {parsed.hostname or ''}{parsed.path}"
                self.main_frame_error_category = "unexpected_navigation"
                await route.abort()
                return
            if main_frame:
                self.main_frame_navigation_urls.append(request.url)
                response = None
                try:
                    response = await _fetch_main_frame_response_without_redirect(route)
                    if response is None:
                        return
                    status = int(response.status)
                    self.last_main_frame_response_status = status
                    if 300 <= status < 400 and status != 304:
                        self.main_frame_error_category = "http_redirect"
                        self.navigation_violation = (
                            f"GET {(parsed.hostname or '').lower()}{parsed.path} redirect {status}"
                        )
                        await route.abort()
                        return
                    await route.fulfill(response=response)
                except Exception as exc:  # noqa: BLE001 - fail closed without exposing call-log text
                    self.main_frame_error_category = _safe_route_error_category(exc)
                    detail = (
                        "document fetch timed out"
                        if self.main_frame_error_category == "timeout"
                        else "document fetch failed"
                    )
                    self.navigation_violation = (
                        f"GET {(parsed.hostname or '').lower()}{parsed.path} {detail}"
                    )
                    await route.abort()
                finally:
                    if response is not None:
                        try:
                            await response.dispose()
                        except PlaywrightError:
                            self.main_frame_error_category = "response_cleanup_failed"
                            self.navigation_violation = (
                                f"GET {(parsed.hostname or '').lower()}{parsed.path} document cleanup failed"
                            )
                return
        await route.fallback()

    def require_navigation(self, expected_url: str, prior_count: int | None = None) -> None:
        if (
            not self.main_frame_navigation_urls
            or self.main_frame_navigation_urls[-1] != expected_url
            or (
                prior_count is not None
                and len(self.main_frame_navigation_urls) != prior_count + 1
            )
        ):
            raise UnknownPageStateError(
                "HERO'S WEB expected document did not pass through the guarded main-frame route"
            )

    def raise_if_failed(self) -> None:
        if self.unexpected_write is not None:
            raise UnknownPageStateError(
                "HERO'S WEB blocked an unapproved request write before entry"
            )
        if self.navigation_violation is not None:
            raise UnknownPageStateError(
                "HERO'S WEB blocked an unapproved navigation"
            )


class HeroswebAdapter(SiteAdapter):
    """Capture free episodes and identity-bound, directly readable Batch targets."""

    page_change_timeout_ms = PAGE_CHANGE_TIMEOUT_MS

    def __init__(self) -> None:
        self._access_strategy: AccessStrategy = "auto"
        self._expected_work_id: str | None = None
        self._expected_episode_id: str | None = None
        self._work_key: str | None = None
        self._work_id: str | None = None
        self._episode_id: str | None = None
        self._target_url: str | None = None
        self._work_title: str | None = None
        self._episode_title: str | None = None
        self._episode_position: int | None = None
        self._free_proof: dict[str, object] | None = None
        self._route_guard: HeroswebEpisodeRouteGuard | None = None
        self._blocked_external_writes: list[str] = []
        self._service_worker_controlled: bool | None = None
        self._preflight_access_stop: dict[str, object] | None = None
        self._layout: _ViewerLayout | None = None
        self._captured_slots: list[int] = []
        self._expected_seek_after_turn: int | None = None
        self._expected_slots_after_turn: tuple[int, ...] | None = None
        self._prior_observation_signature: tuple[object, ...] | None = None
        self._last_observation: dict[str, object] | None = None
        self._last_state: PageState | None = None
        self._last_capture: dict[str, object] | None = None
        self._capture_diagnostics: dict[str, object] = {"mode": "not_started"}
        self._ended = False

    def get_access_profile(self) -> AccessProfile:
        return herosweb_access_profile()

    def get_initialize_timeout_ms(self, default_ms: int) -> int:
        del default_ms
        return int(MAX_PREFLIGHT_SECONDS * 1_000)

    def get_page_change_timeout_ms(self, default_ms: int) -> int:
        return max(default_ms, PAGE_CHANGE_TIMEOUT_MS)

    async def prepare_page(self, page: Page) -> None:
        if self._route_guard is not None:
            raise UnknownPageStateError("HERO'S WEB route guard was already installed")
        try:
            self._preflight_access_stop = None
            page.on("response", self._on_preflight_response)
            await page.add_init_script(_OBSERVER_INIT_SCRIPT)
            self._route_guard = HeroswebEpisodeRouteGuard(page, episode_id="")
            self._route_guard.blocked_external_writes = self._blocked_external_writes
            await page.route("**/*", self._route_guard)
        except PlaywrightError as exc:
            self._remove_preflight_access_listener(page)
            self._preflight_access_stop = None
            self._route_guard = None
            raise UnknownPageStateError("HERO'S WEB safe viewer guard could not be installed") from exc

    async def configure_run(self, page: Page, access_strategy: AccessStrategy) -> None:
        del page
        self._access_strategy = access_strategy
        if access_strategy not in {"auto", "direct"}:
            raise UnsupportedAccessStrategyError(
                "HERO'S WEB Viewer supports auto/direct free access only"
            )

    async def configure_quota_resource(self, page: Page, quota_resource: str | None) -> None:
        del page
        if self._access_strategy == "quota" or quota_resource is not None:
            raise UnsupportedAccessStrategyError(
                "HERO'S WEB ticket/quota entry is not implemented"
            )

    async def configure_target_identity(self, external_id: str, work_key: str) -> None:
        match = EXTERNAL_ID_RE.fullmatch(external_id)
        if match is None or not isinstance(work_key, str) or not work_key.strip():
            raise UnknownPageStateError("HERO'S WEB Catalog target identity is malformed")
        self._expected_work_id = match.group("work")
        self._expected_episode_id = match.group("episode")
        self._work_key = work_key

    def resolve_initial_navigation_url(self, source_url: str) -> str:
        episode_id = parse_herosweb_episode_url(source_url)
        if (
            episode_id is None
            or source_url != f"{BASE_URL}/episodes/{episode_id}"
            or not EPISODE_ID_RE.fullmatch(episode_id)
        ):
            raise UnknownPageStateError("HERO'S WEB requires an exact canonical episode URL")
        if self._expected_episode_id is not None and self._expected_episode_id != episode_id:
            raise UnknownPageStateError("HERO'S WEB episode URL differs from its Catalog target")
        if self._expected_work_id is not None and self._work_key is None:
            raise UnknownPageStateError("HERO'S WEB Catalog Work binding is incomplete")
        self._episode_id = episode_id
        self._target_url = source_url
        if self._route_guard is not None:
            self._route_guard.episode_id = episode_id
            self._route_guard.allow_navigation(source_url)
        return source_url

    async def initialize(self, page: Page) -> None:
        try:
            await self._initialize_page(page)
        finally:
            self._remove_preflight_access_listener(page)
            self._preflight_access_stop = None

    async def _initialize_page(self, page: Page) -> None:
        if self._target_url is None or self._episode_id is None:
            raise UnknownPageStateError("HERO'S WEB episode target was not validated")
        self._raise_if_preflight_access_stopped()
        if page.url != self._target_url:
            raise UnknownPageStateError("HERO'S WEB initial document left its exact episode route")
        route_guard = self._route_guard
        if route_guard is None:
            raise UnknownPageStateError("HERO'S WEB main-frame route guard is unavailable")
        route_guard.require_navigation(self._target_url)
        await self._assert_no_service_worker_controller(page)
        self._captured_slots = []
        self._layout = None
        self._last_observation = None
        self._last_state = None
        self._last_capture = None
        self._expected_seek_after_turn = None
        self._expected_slots_after_turn = None
        self._prior_observation_signature = None
        self._ended = False
        self._capture_diagnostics = {"mode": "not_started", "pages": []}

        header = await self._read_episode_header(page)
        self._raise_if_preflight_access_stopped()
        header_work_id = self._work_id_from_header(header)
        if self._expected_work_id is not None and header_work_id != self._expected_work_id:
            raise UnknownPageStateError("HERO'S WEB episode header differs from its Catalog Work")
        self._work_id = header_work_id

        if self._expected_work_id is not None and self._access_strategy == "direct":
            # Batch selected a free or active-rental Source. Verify the current exact
            # episode gate and Viewer instead of traversing the Work listing.
            await self._validate_episode_entry(page)
            self._free_proof = {
                "source": "catalog_direct_episode_entry",
                "work_id": self._work_id,
                "episode_id": self._episode_id,
                "episode_path": urlsplit(self._target_url).path,
                "access_strategy": "direct",
            }
        else:
            access = await self._prove_current_free_episode(page)
            if access != "free":
                raise UnknownPageStateError("HERO'S WEB current episode is not positively free")

            # Manual entry returns after the read-only same-Work preflight.
            await page.wait_for_timeout(RANGE_PACING_MS)
            self._raise_if_route_guard_failed()
            self._raise_if_preflight_access_stopped()
            prior_navigation_count = len(route_guard.main_frame_navigation_urls)
            self._allow_navigation(self._target_url)
            response = await page.goto(
                self._target_url, wait_until="domcontentloaded", timeout=20_000
            )
            route_guard.require_navigation(self._target_url, prior_navigation_count)
            await self._assert_no_service_worker_controller(page)
            self._raise_if_route_guard_failed()
            self._raise_if_preflight_access_stopped()
            if (
                response is None
                or response.status not in (*range(200, 300), 304)
                or page.url != self._target_url
            ):
                raise UnknownPageStateError("HERO'S WEB direct free entry changed its target route")
        await page.wait_for_timeout(250)
        self._raise_if_preflight_access_stopped()
        await self._validate_episode_entry(page)
        self._raise_if_preflight_access_stopped()
        await self._wait_for_viewer_root(page)
        self._raise_if_preflight_access_stopped()
        await self._wait_for_loaded_viewer_structure(page)
        self._raise_if_preflight_access_stopped()
        first = await self._wait_for_stable_observation(
            page,
            expected_seek=None,
            timeout_seconds=MAX_VIEWER_SETTLE_SECONDS,
            require_ready=False,
        )
        self._raise_if_preflight_access_stopped()
        layout = self._parse_layout(first)
        self._layout = layout
        if layout.seek_min != 1 or layout.seek_step != 2:
            raise UnknownPageStateError("HERO'S WEB public seek geometry changed")
        if layout.seek_max != _spread_seek_max(len(layout.wrapper_node_ids)):
            raise UnknownPageStateError("HERO'S WEB seek range does not match its frozen wrappers")

        current_seek = self._seek_value(first)
        if current_seek != layout.seek_max:
            await self._set_seek_value(page, layout.seek_max)
        first = await self._wait_for_stable_observation(
            page,
            expected_seek=layout.seek_max,
            timeout_seconds=MAX_VIEWER_SETTLE_SECONDS,
            require_ready=True,
        )
        self._assert_frozen_layout(first)
        self._require_first_body_state(first)
        self._last_observation = first
        self._last_state = PageState.CONTENT
        self._capture_diagnostics.update(
            {
                "mode": "rendered_canvas_png",
                "source_native_proven": False,
                "native_pixels_proven": False,
                "original_bytes_proven": False,
                "body_slot_count": len(layout.body_slots),
                "wrapper_count": len(layout.roles),
                "seek": {
                    "min": layout.seek_min,
                    "max": layout.seek_max,
                    "step": layout.seek_step,
                    "value": self._seek_value(first),
                },
            }
        )

    async def _prove_current_free_episode(self, page: Page) -> str:
        work_id = self._work_id
        episode_id = self._episode_id
        if work_id is None or episode_id is None:
            raise UnknownPageStateError("HERO'S WEB free preflight identity is incomplete")
        work_url = f"{BASE_URL}/series/{work_id}"
        auth = _CurrentDocumentAuth(page)
        try:
            await self._navigate_preflight(page, auth, work_url)
            authenticated = await self._current_page_authenticated(
                page, auth, expected_url=work_url
            )
            base_snapshot = await self._stable_work_header_snapshot(page, work_url)
            title, ranges = self._validated_work_header(
                base_snapshot, expected_url=work_url, work_id=work_id
            )
            self._work_title = title
            if not ranges or len(ranges) > MAX_PREFLIGHT_RANGES:
                raise UnknownPageStateError(
                    "HERO'S WEB same-Work free preflight exceeds its observed range bound"
                )
            for index, episode_range in enumerate(ranges):
                self._raise_if_preflight_access_stopped()
                self._raise_if_route_guard_failed()
                await page.wait_for_timeout(RANGE_PACING_MS)
                self._raise_if_preflight_access_stopped()
                self._raise_if_route_guard_failed()
                await self._navigate_preflight(page, auth, episode_range.url)
                authenticated = await self._current_page_authenticated(
                    page, auth, expected_url=episode_range.url
                )
                snapshot = await self._stable_listing_snapshot(page, episode_range.url)
                current_title, rows = self._validated_rows(
                    snapshot,
                    expected_url=episode_range.url,
                    work_id=work_id,
                    first_position=episode_range.start_position,
                    authenticated=authenticated,
                )
                if current_title != title:
                    raise UnknownPageStateError("HERO'S WEB Work title changed during free preflight")
                if len(rows) != episode_range.end_position - episode_range.start_position + 1:
                    raise UnknownPageStateError(
                        "HERO'S WEB range row count disagrees with its declared interval"
                    )
                match = self._one_target_row(rows, episode_id)
                if match is not None:
                    self._episode_position = match.global_position
                    return self._accept_free_row(match, authenticated, page_url=episode_range.url)
                if index + 1 < len(ranges):
                    self._raise_if_preflight_access_stopped()
            raise UnknownPageStateError(
                "HERO'S WEB episode is missing from its current same-Work listing"
            )
        except AccessStopError:
            raise
        except UnknownPageStateError:
            raise
        except (PlaywrightError, TimeoutError, ValueError) as exc:
            self._raise_if_preflight_access_stopped()
            self._raise_if_route_guard_failed()
            raise UnknownPageStateError(
                "HERO'S WEB fresh same-Work free preflight did not complete"
            ) from exc
        finally:
            await auth.close()

    async def _stable_work_header_snapshot(
        self, page: Page, expected_url: str
    ) -> dict[str, object]:
        try:
            await page.wait_for_function(
                """() => document.querySelectorAll('.series-h').length === 1 &&
                  document.querySelectorAll('.series-sort').length === 1 &&
                  document.querySelectorAll('.series-sort a.series-sort-link').length > 0""",
                timeout=DOM_TIMEOUT_MS,
            )
        except (PlaywrightError, TimeoutError) as exc:
            self._raise_if_preflight_access_stopped()
            self._raise_if_route_guard_failed()
            raise UnknownPageStateError(
                "HERO'S WEB Work header or range controls did not settle"
            ) from exc

        deadline = asyncio.get_running_loop().time() + DOM_TIMEOUT_MS / 1_000
        previous: tuple[object, ...] | None = None
        stable_fields = (
            "canonicalCount",
            "canonicals",
            "titles",
            "mainCount",
            "rangeContainerCount",
            "rangeLinks",
        )
        while asyncio.get_running_loop().time() < deadline:
            self._raise_if_preflight_access_stopped()
            self._raise_if_route_guard_failed()
            if page.url != expected_url:
                raise UnknownPageStateError(
                    "HERO'S WEB preflight left its exact Work route"
                )
            try:
                snapshot = await asyncio.wait_for(
                    page.evaluate(_snapshot_script()), timeout=5.0
                )
            except (PlaywrightError, TimeoutError) as exc:
                self._raise_if_preflight_access_stopped()
                raise UnknownPageStateError(
                    "HERO'S WEB Work header snapshot was unavailable"
                ) from exc
            self._validated_work_header(
                snapshot,
                expected_url=expected_url,
                work_id=self._work_id or "",
            )
            signature = tuple(snapshot.get(field) for field in stable_fields)
            if signature == previous:
                self._raise_if_preflight_access_stopped()
                return snapshot
            previous = signature
            await page.wait_for_timeout(STABILITY_INTERVAL_MS)
        self._raise_if_preflight_access_stopped()
        raise UnknownPageStateError(
            "HERO'S WEB Work header did not stabilize in time"
        )

    @staticmethod
    def _validated_work_header(
        snapshot: object, *, expected_url: str, work_id: str
    ):
        try:
            return _validate_work_header_snapshot(
                snapshot, expected_url=expected_url, work_id=work_id
            )
        except Exception as exc:
            raise UnknownPageStateError(
                "HERO'S WEB same-Work header or range map is malformed"
            ) from exc

    async def _navigate_preflight(
        self, page: Page, auth: _CurrentDocumentAuth, expected_url: str
    ) -> None:
        self._raise_if_preflight_access_stopped()
        self._raise_if_route_guard_failed()
        await self._assert_no_service_worker_controller(page)
        guard = self._route_guard
        if guard is None:
            raise UnknownPageStateError("HERO'S WEB main-frame route guard is unavailable")
        prior_navigation_count = len(guard.main_frame_navigation_urls)
        auth.begin_document(expected_url)
        self._allow_navigation(expected_url)
        response = await page.goto(expected_url, wait_until="domcontentloaded", timeout=20_000)
        guard.require_navigation(expected_url, prior_navigation_count)
        await self._assert_no_service_worker_controller(page)
        self._raise_if_preflight_access_stopped()
        self._raise_if_route_guard_failed()
        if (
            response is None
            or response.status not in (*range(200, 300), 304)
            or page.url != expected_url
        ):
            if response is not None and response.status in {403, 429}:
                reason = "http_403" if response.status == 403 else "http_429"
                host = (urlsplit(expected_url).hostname or "heros-web.com").lower()
                path = urlsplit(expected_url).path
                raise AccessStopError(
                    reason=reason,
                    site="herosweb",
                    url=f"https://{host}{path}",
                    host=host,
                    status=response.status,
                )
            raise UnknownPageStateError("HERO'S WEB preflight navigation changed its target")
        self._raise_if_preflight_access_stopped()

    async def _stable_listing_snapshot(
        self, page: Page, expected_url: str
    ) -> dict[str, object]:
        deadline = asyncio.get_running_loop().time() + DOM_TIMEOUT_MS / 1_000
        previous: dict[str, object] | None = None
        while asyncio.get_running_loop().time() < deadline:
            self._raise_if_preflight_access_stopped()
            self._raise_if_route_guard_failed()
            if page.url != expected_url:
                raise UnknownPageStateError("HERO'S WEB preflight left its exact Work route")
            try:
                snapshot = await asyncio.wait_for(
                    page.evaluate(_snapshot_script()), timeout=5.0
                )
            except (PlaywrightError, TimeoutError) as exc:
                self._raise_if_preflight_access_stopped()
                raise UnknownPageStateError("HERO'S WEB preflight snapshot was unavailable") from exc
            if not isinstance(snapshot, dict):
                raise UnknownPageStateError("HERO'S WEB preflight snapshot was malformed")
            canonicals = snapshot.get("canonicals")
            ready = (
                canonicals == [expected_url]
                and snapshot.get("mainCount") == 1
                and snapshot.get("rootCount") == snapshot.get("documentRootCount")
                and snapshot.get("rootCount", 0) > 0
                and snapshot.get("rangeContainerCount") == 1
                and snapshot.get("allRowCount") == snapshot.get("rootRowCount")
            )
            if ready and previous == snapshot:
                self._raise_if_preflight_access_stopped()
                return snapshot
            previous = snapshot if ready else None
            await page.wait_for_timeout(
                min(STABILITY_INTERVAL_MS, max(1, int((deadline - asyncio.get_running_loop().time()) * 1_000)))
            )
        self._raise_if_preflight_access_stopped()
        raise UnknownPageStateError("HERO'S WEB preflight listing did not stabilize in time")

    async def _current_page_authenticated(
        self, page: Page, auth: _CurrentDocumentAuth, *, expected_url: str
    ) -> bool:
        await auth.wait_for_current_response()
        self._raise_if_preflight_access_stopped()
        if (
            page.url != expected_url
            or auth.expected_url != expected_url
            or auth.session_user_present is not True
        ):
            return False
        deadline = asyncio.get_running_loop().time() + AUTH_HEADER_SETTLE_SECONDS
        previous: dict[str, object] | None = None
        while asyncio.get_running_loop().time() < deadline:
            self._raise_if_preflight_access_stopped()
            self._raise_if_route_guard_failed()
            if page.url != expected_url or auth.expected_url != expected_url:
                return False
            try:
                current = await asyncio.wait_for(
                    page.evaluate(_auth_header_script()), timeout=2.0
                )
            except (PlaywrightError, TimeoutError):
                self._raise_if_preflight_access_stopped()
                self._raise_if_route_guard_failed()
                return False
            if (
                current == previous
                and _positive_auth_header(current)
                and auth.session_user_present is True
            ):
                return True
            previous = current if isinstance(current, dict) else None
            await page.wait_for_timeout(
                min(
                    STABILITY_INTERVAL_MS,
                    max(
                        1,
                        int(
                            (deadline - asyncio.get_running_loop().time()) * 1_000
                        ),
                    ),
                )
            )
        self._raise_if_preflight_access_stopped()
        self._raise_if_route_guard_failed()
        return False

    def _validated_rows(
        self,
        snapshot: dict[str, object],
        *,
        expected_url: str,
        work_id: str,
        first_position: int,
        authenticated: bool,
    ):
        try:
            return _validate_snapshot(
                snapshot,
                expected_url=expected_url,
                work_id=work_id,
                first_position=first_position,
                authenticated=authenticated,
            )
        except Exception as exc:
            raise UnknownPageStateError(
                "HERO'S WEB same-Work episode proof is malformed or ambiguous"
            ) from exc

    @staticmethod
    def _one_target_row(rows, episode_id: str):
        matches = [row for row in rows if row.episode_id == episode_id]
        if len(matches) > 1:
            raise UnknownPageStateError("HERO'S WEB same-Work proof duplicated the target episode")
        return matches[0] if matches else None

    def _accept_free_row(self, row, authenticated: bool, *, page_url: str) -> str:
        if row.access_mode != "free":
            raise UnknownPageStateError(
                "HERO'S WEB exact current episode row is not positively free"
            )
        self._episode_title = row.title
        if urlsplit(page_url).path == f"/series/{self._work_id}":
            self._episode_position = None
        elif row.global_position > 0:
            self._episode_position = row.global_position
        self._free_proof = {
            "source": "fresh_same_work_listing",
            "work_id": self._work_id,
            "episode_id": self._episode_id,
            "listing_path": urlsplit(page_url).path,
            "authenticated": authenticated,
            "access_mode": row.access_mode,
        }
        return row.access_mode

    async def _read_episode_header(self, page: Page) -> dict[str, object]:
        try:
            value = await asyncio.wait_for(
                page.evaluate(_EPISODE_ENTRY_SCRIPT), timeout=5.0
            )
        except (PlaywrightError, TimeoutError) as exc:
            raise UnknownPageStateError("HERO'S WEB episode header was unavailable") from exc
        if not isinstance(value, dict):
            raise UnknownPageStateError("HERO'S WEB episode header was malformed")
        return value

    async def _assert_no_service_worker_controller(self, page: Page) -> None:
        try:
            state = await asyncio.wait_for(
                page.evaluate(
                    """() => ({
                      supported: 'serviceWorker' in navigator,
                      controlled: 'serviceWorker' in navigator
                        ? navigator.serviceWorker.controller !== null
                        : false
                    })"""
                ),
                timeout=5.0,
            )
        except (PlaywrightError, TimeoutError) as exc:
            raise UnknownPageStateError(
                "HERO'S WEB service-worker route state could not be verified"
            ) from exc
        if not isinstance(state, dict) or state.get("controlled") is not False:
            self._service_worker_controlled = (
                state.get("controlled") if isinstance(state, dict) and isinstance(state.get("controlled"), bool) else None
            )
            raise UnknownPageStateError(
                "HERO'S WEB service-worker-controlled page is not supported"
            )
        self._service_worker_controlled = False

    def _work_id_from_header(self, header: dict[str, object]) -> str:
        target_url = self._target_url
        episode_id = self._episode_id
        if target_url is None or episode_id is None:
            raise UnknownPageStateError("HERO'S WEB episode header has no target binding")
        work_path = header.get("workPath")
        work_id = parse_herosweb_work_url(f"{BASE_URL}{work_path}") if isinstance(work_path, str) else None
        if (
            header.get("url") != target_url
            or header.get("episodeId") != episode_id
            or header.get("canonical") != [target_url]
            or header.get("headerCount") != 1
            or header.get("workLinkCount") != 1
            or work_id is None
        ):
            raise UnknownPageStateError("HERO'S WEB exact episode header did not bind one Work")
        return work_id

    async def _validate_episode_entry(self, page: Page) -> None:
        header = await self._read_episode_header(page)
        work_id = self._work_id_from_header(header)
        if work_id != self._work_id:
            raise UnknownPageStateError("HERO'S WEB direct episode header changed Work identity")
        if (
            header.get("chargeGateCount") != 0
            or header.get("visibleLoginActionCount") != 0
            or header.get("viewerFrameCount") != 0
        ):
            raise UnknownPageStateError("HERO'S WEB direct episode showed an access gate or nested frame")

    def _on_preflight_response(self, response) -> None:
        if self._preflight_access_stop is not None:
            return
        try:
            status = int(response.status)
            url = str(response.url)
            parsed = urlsplit(url)
            if status in {403, 429} and is_herosweb_relevant_host(url):
                self._preflight_access_stop = {
                    "host": (parsed.hostname or "").lower(),
                    "path": PurePosixPath(parsed.path).as_posix(),
                    "status": status,
                }
        except (AttributeError, TypeError, ValueError):
            return

    def _remove_preflight_access_listener(self, page: Page) -> None:
        try:
            page.remove_listener("response", self._on_preflight_response)
        except PlaywrightError:
            pass

    def _raise_if_preflight_access_stopped(self) -> None:
        stop = self._preflight_access_stop
        if stop is None:
            return
        host = stop.get("host")
        path = stop.get("path")
        status = stop.get("status")
        if (
            not isinstance(host, str)
            or not isinstance(path, str)
            or status not in {403, 429}
        ):
            raise UnknownPageStateError("HERO'S WEB preflight access stop was malformed")
        reason = "http_403" if status == 403 else "http_429"
        raise AccessStopError(
            reason=reason,
            site="herosweb",
            url=f"https://{host}{path}",
            host=host,
            status=status,
        )

    def _allow_navigation(self, url: str) -> None:
        guard = self._route_guard
        if guard is None:
            raise UnknownPageStateError("HERO'S WEB main-frame route guard is unavailable")
        guard.allow_navigation(url)

    def _raise_if_route_guard_failed(self) -> None:
        if self._route_guard is not None:
            self._route_guard.raise_if_failed()

    async def _wait_for_viewer_root(self, page: Page) -> None:
        try:
            await page.wait_for_function(
                "() => document.querySelectorAll('.-cv').length === 1 && "
                "document.querySelectorAll('.-cv-pages-wrap').length === 1 && "
                "document.querySelectorAll('.-cv-pages').length === 1",
                timeout=int(MAX_VIEWER_SETTLE_SECONDS * 1_000),
            )
        except (PlaywrightError, TimeoutError) as exc:
            self._raise_if_route_guard_failed()
            raise UnknownPageStateError("HERO'S WEB direct episode did not expose its Viewer") from exc

    async def _wait_for_loaded_viewer_structure(self, page: Page) -> None:
        """Wait only through the observed explicit loading shell before parsing layout."""

        self._raise_if_route_guard_failed()
        self._raise_if_preflight_access_stopped()
        try:
            raw = await asyncio.wait_for(
                page.evaluate(_VIEWER_SNAPSHOT_SCRIPT), timeout=5.0
            )
        except (PlaywrightError, TimeoutError) as exc:
            self._raise_if_route_guard_failed()
            self._raise_if_preflight_access_stopped()
            raise UnknownPageStateError(
                "HERO'S WEB loading Viewer state could not be observed"
            ) from exc
        if not isinstance(raw, dict) or raw.get("url") != self._target_url or raw.get(
            "canonical"
        ) != [self._target_url]:
            raise UnknownPageStateError(
                "HERO'S WEB loading Viewer identity changed"
            )
        root_modes = raw.get("rootClassTokens")
        if not isinstance(root_modes, list) or "mode-loading" not in root_modes:
            return
        seek = raw.get("seek")
        wrappers = raw.get("wrappers")
        if (
            raw.get("rootCount") != 1
            or raw.get("pagesWrapCount") != 1
            or raw.get("pagesRootCount") != 1
            or raw.get("viewerTreeValid") is not True
            or wrappers != []
            or not isinstance(seek, list)
            or len(seek) != 1
            or not isinstance(seek[0], dict)
            or seek[0].get("min") != "1"
            or seek[0].get("max") != "1"
            or seek[0].get("step") != "1"
        ):
            raise UnknownPageStateError(
                "HERO'S WEB loading Viewer shell is unfamiliar"
            )
        try:
            await page.wait_for_function(
                r"""expectedUrl => {
                  if (location.href !== expectedUrl) return false;
                  const canonicals = [...document.querySelectorAll('link[rel="canonical"]')];
                  if (canonicals.length !== 1 || canonicals[0].href !== expectedUrl) return false;
                  const roots = [...document.querySelectorAll('.-cv')];
                  const wraps = [...document.querySelectorAll('.-cv-pages-wrap')];
                  const pages = [...document.querySelectorAll('.-cv-pages')];
                  const seeks = [...document.querySelectorAll('input.-cv-input-seek.mode-h')];
                  if (roots.length !== 1 || wraps.length !== 1 || pages.length !== 1 || seeks.length !== 1) return false;
                  if (roots[0].classList.contains('mode-loading')) return false;
                  const wrappers = [...pages[0].children];
                  const seek = seeks[0];
                  return wrappers.length > 1 && Number(seek.min) === 1 && Number(seek.step) === 2 &&
                    Number(seek.max) === 2 * Math.floor((wrappers.length - 1) / 2) + 1;
                }""",
                arg=self._target_url,
                timeout=int(MAX_VIEWER_SETTLE_SECONDS * 1_000),
            )
        except (PlaywrightError, TimeoutError) as exc:
            self._raise_if_route_guard_failed()
            self._raise_if_preflight_access_stopped()
            raise UnknownPageStateError(
                "HERO'S WEB loading Viewer did not expose the observed wrapper/seek structure"
            ) from exc
        self._raise_if_route_guard_failed()
        self._raise_if_preflight_access_stopped()

    async def _wait_for_stable_observation(
        self,
        page: Page,
        *,
        expected_seek: int | None,
        timeout_seconds: float,
        require_ready: bool,
    ) -> dict[str, object]:
        deadline = asyncio.get_running_loop().time() + timeout_seconds
        previous: tuple[object, ...] | None = None
        while asyncio.get_running_loop().time() < deadline:
            self._raise_if_route_guard_failed()
            self._raise_if_preflight_access_stopped()
            if page.url != self._target_url:
                raise UnknownPageStateError("HERO'S WEB Viewer changed episode during observation")
            try:
                raw = await asyncio.wait_for(
                    page.evaluate(_VIEWER_SNAPSHOT_SCRIPT), timeout=5.0
                )
            except (PlaywrightError, TimeoutError) as exc:
                self._raise_if_preflight_access_stopped()
                raise UnknownPageStateError("HERO'S WEB Viewer observation was unavailable") from exc
            self._raise_if_preflight_access_stopped()
            try:
                layout = self._parse_layout(raw)
            except UnknownPageStateError:
                if not (
                    self._layout is None
                    and self._is_observed_pr_hydration_state(raw)
                ):
                    raise
                await self._validate_episode_entry(page)
                self._raise_if_route_guard_failed()
                self._raise_if_preflight_access_stopped()
                previous = None
                await page.wait_for_timeout(POLL_INTERVAL_MS)
                continue
            if self._layout is not None:
                self._assert_layout_mapping(layout)
            seek_value = self._seek_value(raw)
            if expected_seek is not None and seek_value != expected_seek:
                previous = None
            else:
                signature = self._observation_signature(raw)
                ready = self._observation_is_ready(raw, layout)
                if previous == signature and (ready or not require_ready):
                    self._last_observation = raw
                    return raw
                previous = signature if (ready or not require_ready) else None
            await page.wait_for_timeout(POLL_INTERVAL_MS)
        raise PageChangeTimeoutError("HERO'S WEB Viewer did not settle within its bounded wait")

    def _is_observed_pr_hydration_state(self, raw: object) -> bool:
        """Recognize only the sampled initial hydration signatures awaiting PR."""

        if not isinstance(raw, dict) or raw.get("url") != self._target_url or raw.get(
            "canonical"
        ) != [self._target_url]:
            return False
        if (
            raw.get("rootCount") != 1
            or raw.get("pagesWrapCount") != 1
            or raw.get("pagesRootCount") != 1
            or raw.get("viewerFrameCount") != 0
            or raw.get("viewerTreeValid") is not True
            or not self._style_is_visible(raw.get("rootStyle"))
            or not self._style_is_visible(raw.get("pagesWrapStyle"))
            or not self._style_is_visible(raw.get("pagesRootStyle"))
        ):
            return False
        root_modes = raw.get("rootClassTokens")
        if not isinstance(root_modes, list) or not all(
            isinstance(mode, str) for mode in root_modes
        ):
            return False
        modes = set(root_modes)
        if _ROOT_REQUIRED_MODES - modes != {"mode-has-pr"}:
            return False
        provisional = dict(raw)
        provisional["rootClassTokens"] = [*root_modes, "mode-has-pr"]
        try:
            layout = self._parse_layout(provisional)
        except UnknownPageStateError:
            return False
        wrappers = raw.get("wrappers")
        seek = raw.get("seek")
        if (
            not isinstance(wrappers, list)
            or not 1 < len(wrappers) <= MAX_BODY_PAGES + 6
            or not isinstance(seek, list)
            or len(seek) != 1
            or not isinstance(seek[0], dict)
        ):
            return False
        try:
            seek_min = int(seek[0]["min"])
            seek_max = int(seek[0]["max"])
            seek_step = int(seek[0]["step"])
            seek_value = int(seek[0]["value"])
        except (KeyError, TypeError, ValueError):
            return False
        if (
            seek_min != 1
            or seek_step != 2
            or seek_max != _spread_seek_max(len(wrappers))
            or seek[0].get("disabled") is not False
        ):
            return False
        if seek_value == seek_max:
            if not {"mode-first-page", "mode-top-pr-page"}.issubset(modes):
                return False
            if set(wrappers[0].get("classTokens", [])) != {
                "-cv-page",
                "mode-empty",
                "mode-pr",
                "mode-top-pr",
            }:
                return False
            ci_positions = [
                index
                for index, wrapper in enumerate(wrappers)
                if isinstance(wrapper, dict)
                and "mode-ci" in wrapper.get("classTokens", [])
            ]
            if len(ci_positions) != 1:
                return False
            pending_body_positions = [
                index
                for index, wrapper in enumerate(wrappers)
                if isinstance(wrapper, dict)
                and set(wrapper.get("classTokens", []))
                == {"-cv-page", "mode-loading", "mode-req-render"}
            ]
            return bool(pending_body_positions) and all(
                0 < index < ci_positions[0] for index in pending_body_positions
            )

        # A09 and B12 observed these exact resumed loading profiles. Validate
        # the complete shape above, but never return or save this provisional
        # layout. Keep this limited to the two recorded range/body/seek tuples.
        profile = (len(wrappers), len(layout.body_slots), seek_max, seek_value)
        if profile not in _OBSERVED_RESUMED_PR_PROFILES:
            return False
        wrapper_count, body_count, expected_max, _ = profile
        if (
            layout.seek_max != expected_max
            or layout.body_slots != tuple(range(1, body_count + 1))
            or layout.ci_slot != body_count + 1
            or wrapper_count != body_count + 7
        ):
            return False
        pair_start = ((seek_max - seek_value) // seek_step) * 2
        if pair_start != 4 or layout.roles[pair_start : pair_start + 2] != ("body", "body"):
            return False
        pending_classes = {"-cv-page", "mode-loading", "mode-req-render"}
        for index in (4, 5, 6):
            wrapper = wrappers[index]
            if (
                not isinstance(wrapper, dict)
                or set(wrapper.get("classTokens", [])) != pending_classes
            ):
                return False
        return all(
            isinstance(wrapper, dict)
            and isinstance(wrapper.get("canvases"), list)
            and not wrapper["canvases"]
            for wrapper in wrappers
        )

    def _parse_layout(self, raw: object) -> _ViewerLayout:
        if not isinstance(raw, dict):
            raise UnknownPageStateError("HERO'S WEB Viewer snapshot is malformed")
        if (
            raw.get("url") != self._target_url
            or raw.get("canonical") != [self._target_url]
            or raw.get("rootCount") != 1
            or raw.get("pagesWrapCount") != 1
            or raw.get("pagesRootCount") != 1
            or raw.get("viewerFrameCount") != 0
            or raw.get("viewerTreeValid") is not True
            or not self._style_is_visible(raw.get("rootStyle"))
            or not self._style_is_visible(raw.get("pagesWrapStyle"))
            or not self._style_is_visible(raw.get("pagesRootStyle"))
        ):
            raise UnknownPageStateError("HERO'S WEB Viewer identity or root scope changed")
        viewport = raw.get("viewportRect")
        if (
            not isinstance(viewport, dict)
            or not isinstance(viewport.get("width"), (int, float))
            or not isinstance(viewport.get("height"), (int, float))
            or viewport["width"] <= 0
            or viewport["height"] <= 0
        ):
            raise UnknownPageStateError("HERO'S WEB Viewer has no visible page viewport")
        root_modes = raw.get("rootClassTokens")
        wrappers = raw.get("wrappers")
        seek = raw.get("seek")
        if not isinstance(root_modes, list) or not all(isinstance(item, str) for item in root_modes):
            raise UnknownPageStateError("HERO'S WEB Viewer root classes are malformed")
        if not _ROOT_REQUIRED_MODES.issubset(set(root_modes)):
            raise UnknownPageStateError("HERO'S WEB Viewer layout is not the observed RTL spread")
        if (
            set(root_modes)
            - _ROOT_STRUCTURAL_MODES
            - _ROOT_OPTIONAL_FEATURE_MODES
            - _ROOT_DYNAMIC_MODES
            - {"-cv", "mode-lang-ja", "mode-vh-change"}
        ):
            raise UnknownPageStateError("HERO'S WEB Viewer has an unrecognized root mode")
        if not isinstance(wrappers, list) or not 1 < len(wrappers) <= MAX_BODY_PAGES + 6:
            raise UnknownPageStateError("HERO'S WEB Viewer wrapper count is missing or excessive")
        if not isinstance(seek, list) or len(seek) != 1 or not isinstance(seek[0], dict):
            raise UnknownPageStateError("HERO'S WEB public seek control is missing or duplicated")

        roles: list[str] = []
        wrapper_ids: list[int] = []
        body_slots: list[int] = []
        ci_slots: list[int] = []
        pr_slots: list[int] = []
        good_slots: list[int] = []
        last_slots: list[int] = []
        for index, wrapper in enumerate(wrappers):
            if not isinstance(wrapper, dict) or wrapper.get("tag") != "DIV":
                raise UnknownPageStateError("HERO'S WEB Viewer wrapper is malformed")
            node_id = wrapper.get("nodeId")
            classes = wrapper.get("classTokens")
            if not isinstance(node_id, int) or not isinstance(classes, list) or "-cv-page" not in classes:
                raise UnknownPageStateError("HERO'S WEB Viewer wrapper identity is missing")
            wrapper_ids.append(node_id)
            class_set = set(classes)
            markers = class_set.intersection({"mode-pr", "mode-ci", "mode-good", "mode-last"})
            if len(markers) > 1:
                raise UnknownPageStateError("HERO'S WEB Viewer wrapper has conflicting semantic roles")
            if "mode-pr" in markers:
                expected = {"-cv-page", "mode-empty", "mode-pr"}
                if index == 0:
                    expected.add("mode-top-pr")
                    role = "lead_pr"
                else:
                    role = "pr"
                if class_set != expected:
                    raise UnknownPageStateError("HERO'S WEB PR wrapper role is unfamiliar")
                if role == "pr":
                    pr_slots.append(index)
            elif "mode-ci" in markers:
                if class_set != {"-cv-page", "mode-ci"}:
                    raise UnknownPageStateError("HERO'S WEB CI wrapper role is unfamiliar")
                role = "ci"
                ci_slots.append(index)
            elif "mode-good" in markers:
                if class_set != {"-cv-page", "mode-good"}:
                    raise UnknownPageStateError("HERO'S WEB Good wrapper role is unfamiliar")
                role = "good"
                good_slots.append(index)
            elif "mode-last" in markers:
                if class_set != {"-cv-page", "mode-last"}:
                    raise UnknownPageStateError("HERO'S WEB Last wrapper role is unfamiliar")
                role = "last"
                last_slots.append(index)
            else:
                if class_set - {"-cv-page"} - _BODY_STATE_MODES:
                    raise UnknownPageStateError("HERO'S WEB body wrapper has an unknown role mode")
                role = "body"
                body_slots.append(index)
            roles.append(role)

        if (
            roles[0] != "lead_pr"
            or len(ci_slots) != 1
            or len(good_slots) != 1
            or len(last_slots) != 1
            or len(pr_slots) != 3
            or not body_slots
            or len(body_slots) > MAX_BODY_PAGES
        ):
            raise UnknownPageStateError("HERO'S WEB Viewer role inventory is incomplete or ambiguous")
        ci_slot, good_slot, last_slot = ci_slots[0], good_slots[0], last_slots[0]
        if (
            body_slots != list(range(1, ci_slot))
            or pr_slots != list(range(ci_slot + 1, ci_slot + 4))
            or good_slot != ci_slot + 4
            or last_slot != ci_slot + 5
            or last_slot != len(wrappers) - 1
        ):
            raise UnknownPageStateError("HERO'S WEB body and interstitial order changed")

        seek_node = seek[0]
        try:
            seek_min = int(seek_node["min"])
            seek_max = int(seek_node["max"])
            seek_step = int(seek_node["step"])
        except (KeyError, TypeError, ValueError) as exc:
            raise UnknownPageStateError("HERO'S WEB seek range is malformed") from exc
        seek_node_id = seek_node.get("nodeId")
        if not isinstance(seek_node_id, int):
            raise UnknownPageStateError("HERO'S WEB seek node identity is missing")
        try:
            seek_value = int(seek_node["value"])
        except (KeyError, TypeError, ValueError) as exc:
            raise UnknownPageStateError("HERO'S WEB seek value is malformed") from exc
        root_id, wrap_id, pages_id = (
            raw.get("rootNodeId"), raw.get("pagesWrapNodeId"), raw.get("pagesRootNodeId")
        )
        if not all(isinstance(item, int) for item in (root_id, wrap_id, pages_id)):
            raise UnknownPageStateError("HERO'S WEB Viewer container identity is missing")
        if (
            seek_min != 1
            or seek_step != 2
            or seek_node.get("disabled") is not False
            or seek_max <= seek_min
            or seek_value < seek_min
            or seek_value > seek_max
            or (seek_value - seek_min) % seek_step
            or (seek_max - seek_min) % seek_step
            or seek_max != _spread_seek_max(len(wrappers))
            or len(wrapper_ids) != len(set(wrapper_ids))
        ):
            raise UnknownPageStateError("HERO'S WEB public seek and wrapper range disagree")
        structural = tuple(sorted(set(root_modes).intersection(_ROOT_STRUCTURAL_MODES)))
        return _ViewerLayout(
            root_node_id=root_id,
            pages_wrap_node_id=wrap_id,
            pages_root_node_id=pages_id,
            wrapper_node_ids=tuple(wrapper_ids),
            roles=tuple(roles),
            body_slots=tuple(body_slots),
            ci_slot=ci_slot,
            pr_slots=tuple(pr_slots),
            good_slot=good_slot,
            last_slot=last_slot,
            seek_node_id=seek_node_id,
            seek_min=seek_min,
            seek_max=seek_max,
            seek_step=seek_step,
            root_structural_modes=structural,
        )

    def _assert_frozen_layout(self, raw: dict[str, object]) -> None:
        if self._layout is None:
            raise UnknownPageStateError("HERO'S WEB Viewer mapping was not frozen")
        self._assert_layout_mapping(self._parse_layout(raw))

    def _assert_layout_mapping(self, layout: _ViewerLayout) -> None:
        if layout != self._layout:
            raise UnknownPageStateError("HERO'S WEB Viewer role or DOM node mapping changed")

    @staticmethod
    def _seek_value(raw: dict[str, object]) -> int:
        seek = raw.get("seek")
        if not isinstance(seek, list) or len(seek) != 1 or not isinstance(seek[0], dict):
            raise UnknownPageStateError("HERO'S WEB public seek control disappeared")
        try:
            return int(seek[0]["value"])
        except (KeyError, TypeError, ValueError) as exc:
            raise UnknownPageStateError("HERO'S WEB public seek value is malformed") from exc

    def _active_slots(self, raw: dict[str, object]) -> tuple[int, ...]:
        layout = self._layout or self._parse_layout(raw)
        wrappers = raw.get("wrappers")
        if not isinstance(wrappers, list) or len(wrappers) != len(layout.roles):
            raise UnknownPageStateError("HERO'S WEB Viewer wrapper list changed")
        result: list[int] = []
        for index, wrapper in enumerate(wrappers):
            if not isinstance(wrapper, dict):
                raise UnknownPageStateError("HERO'S WEB Viewer wrapper observation is malformed")
            intersection = wrapper.get("intersection")
            if not isinstance(intersection, (int, float)):
                raise UnknownPageStateError("HERO'S WEB Viewer wrapper geometry is malformed")
            if intersection >= 0.98 and self._style_is_visible(wrapper.get("style")):
                result.append(index)
        return tuple(result)

    @staticmethod
    def _style_is_visible(value: object) -> bool:
        if not isinstance(value, dict):
            return False
        try:
            opacity = float(value.get("opacity", 0))
        except (TypeError, ValueError):
            return False
        return (
            value.get("display") not in {None, "none"}
            and value.get("visibility") not in {None, "hidden", "collapse"}
            and opacity > 0
        )

    def _active_body_slots(self, raw: dict[str, object]) -> tuple[int, ...]:
        layout = self._layout or self._parse_layout(raw)
        active = set(self._active_slots(raw))
        return tuple(slot for slot in layout.body_slots if slot in active)

    def _observation_is_ready(self, raw: dict[str, object], layout: _ViewerLayout) -> bool:
        seek_value = self._seek_value(raw)
        active = self._active_slots(raw)
        if not active:
            return False
        for slot in active:
            role = layout.roles[slot]
            if role == "body":
                wrapper = raw["wrappers"][slot]
                classes = set(wrapper.get("classTokens", []))
                canvases = wrapper.get("canvases")
                if (
                    not {"mode-loaded", "mode-rendered"}.issubset(classes)
                    or not isinstance(canvases, list)
                    or len(canvases) != 1
                ):
                    return False
                canvas = canvases[0]
                if (
                    not isinstance(canvas, dict)
                    or canvas.get("width", 0) <= 0
                    or canvas.get("height", 0) <= 0
                    or canvas.get("intersection", 0) < 0.98
                    or not self._style_is_visible(canvas.get("style"))
                    or not isinstance(canvas.get("nodeId"), int)
                    or not isinstance(canvas.get("drawEpoch"), int)
                    or canvas.get("drawEpoch", 0) <= 0
                    or type(canvas.get("generation")) is not int
                    or canvas.get("generation", -1) < 0
                ):
                    return False
            elif role == "lead_pr":
                if seek_value != layout.seek_max:
                    return False
            elif role == "ci":
                active_body = self._active_body_slots(raw)
                if active_body:
                    if active_body[-1] != layout.body_slots[-1]:
                        return False
                elif tuple(self._captured_slots) != layout.body_slots:
                    return False
            elif role in {"pr", "good", "last"}:
                if (
                    role != "last"
                    and not self._active_body_slots(raw)
                    and tuple(self._captured_slots) != layout.body_slots
                ):
                    return False
                continue
            else:
                return False
        return True

    def _observation_signature(self, raw: dict[str, object]) -> tuple[object, ...]:
        layout = self._layout or self._parse_layout(raw)
        wrappers = raw.get("wrappers")
        if not isinstance(wrappers, list):
            raise UnknownPageStateError("HERO'S WEB Viewer wrappers disappeared")
        dynamic_root = tuple(
            sorted(set(raw.get("rootClassTokens", [])).intersection(_ROOT_DYNAMIC_MODES))
        )
        page_signature = tuple(
            (
                wrapper.get("nodeId"),
                wrapper.get("rect"),
                wrapper.get("intersection"),
                tuple(sorted(set(wrapper.get("classTokens", [])).intersection(_BODY_STATE_MODES))),
                tuple(
                    (
                        canvas.get("nodeId"),
                        canvas.get("width"),
                        canvas.get("height"),
                        canvas.get("rect"),
                        canvas.get("intersection"),
                        canvas.get("drawEpoch"),
                        canvas.get("generation"),
                    )
                    for canvas in wrapper.get("canvases", [])
                    if isinstance(canvas, dict)
                ),
            )
            for wrapper in wrappers
            if isinstance(wrapper, dict)
        )
        seek = self._seek_value(raw)
        if layout.wrapper_node_ids != tuple(
            wrapper.get("nodeId") for wrapper in wrappers if isinstance(wrapper, dict)
        ):
            raise UnknownPageStateError("HERO'S WEB Viewer wrapper identity changed")
        return (
            raw.get("url"),
            raw.get("canonical"),
            layout.root_node_id,
            dynamic_root,
            seek,
            self._active_slots(raw),
            page_signature,
            raw.get("viewportScrollLeft"),
            raw.get("viewportScrollTop"),
        )

    def _capture_observation_signature(
        self,
        raw: dict[str, object],
        *,
        fully_verified_native_group: bool,
    ) -> tuple[object, ...]:
        if not fully_verified_native_group:
            return self._observation_signature(raw)
        root_tokens = raw.get("rootClassTokens")
        if not isinstance(root_tokens, list) or any(
            not isinstance(token, str) for token in root_tokens
        ):
            raise UnknownPageStateError("HERO'S WEB root class signature is malformed")
        # A05 showed only this navigation UI token disappearing during native
        # materialization. Every other signature field remains strict, and the
        # exception is unavailable to rendered PNG or screenshot captures.
        normalized = dict(raw)
        normalized["rootClassTokens"] = [
            token for token in root_tokens if token != "mode-nav-open"
        ]
        return self._observation_signature(normalized)

    def _require_first_body_state(self, raw: dict[str, object]) -> None:
        if self._layout is None:
            raise UnknownPageStateError("HERO'S WEB first-body layout is missing")
        if self._seek_value(raw) != self._layout.seek_max:
            raise UnknownPageStateError("HERO'S WEB did not rewind to the public seek maximum")
        active_body = self._active_body_slots(raw)
        if not active_body or active_body != self._layout.body_slots[: len(active_body)]:
            raise UnknownPageStateError("HERO'S WEB first visible body slot is not the first body")
        if len(active_body) > 2 or not self._observation_is_ready(raw, self._layout):
            raise UnknownPageStateError("HERO'S WEB first body position did not stabilize")

    async def _set_seek_value(self, page: Page, value: int) -> None:
        layout = self._layout
        if layout is None or value < layout.seek_min or value > layout.seek_max:
            raise UnknownPageStateError("HERO'S WEB requested seek value is outside the frozen range")
        if (value - layout.seek_min) % layout.seek_step:
            raise UnknownPageStateError("HERO'S WEB requested seek value is not a native step")
        try:
            result = await page.evaluate(
                r"""args => {
                  const nodes = [...document.querySelectorAll('input[type="range"]')];
                  if (nodes.length !== 1 || nodes[0].__hwebSeekNode !== undefined) return false;
                  const observer = window.__hwebCaptureObserver;
                  if (!observer || observer.nodeId(nodes[0]) !== args.nodeId) return false;
                  const node = nodes[0];
                  if (Number(node.min) !== args.min || Number(node.max) !== args.max ||
                      Number(node.step) !== args.step || node.disabled) return false;
                  const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')?.set;
                  if (!setter) return false;
                  setter.call(node, String(args.value));
                  node.dispatchEvent(new Event('input', {bubbles:true}));
                  node.dispatchEvent(new Event('change', {bubbles:true}));
                  return Number(node.value) === args.value;
                }""",
                {
                    "nodeId": layout.seek_node_id,
                    "min": layout.seek_min,
                    "max": layout.seek_max,
                    "step": layout.seek_step,
                    "value": value,
                },
            )
        except (PlaywrightError, TimeoutError) as exc:
            raise UnknownPageStateError("HERO'S WEB public seek control could not be moved") from exc
        if result is not True:
            raise UnknownPageStateError("HERO'S WEB public seek control rejected its observed step")

    async def detect_state(self, page: Page) -> PageState:
        self._raise_if_route_guard_failed()
        if self._ended:
            return PageState.END
        if page.url != self._target_url:
            raise UnknownPageStateError("HERO'S WEB Viewer changed to another episode")
        header = await self._read_episode_header(page)
        if self._work_id_from_header(header) != self._work_id:
            raise UnknownPageStateError("HERO'S WEB Viewer header changed its Work")
        if (
            header.get("chargeGateCount") != 0
            or header.get("visibleLoginActionCount") != 0
            or header.get("viewerFrameCount") != 0
        ):
            raise UnknownPageStateError("HERO'S WEB Viewer displayed a login or access gate")
        raw = await self._read_viewer_snapshot(page)
        self._assert_frozen_layout(raw)
        self._last_observation = raw
        layout = self._layout
        if layout is None:
            raise UnknownPageStateError("HERO'S WEB Viewer layout was not initialized")
        active = self._active_slots(raw)
        active_body = self._active_body_slots(raw)
        active_roles = {layout.roles[slot] for slot in active}
        if any(layout.roles[slot] == "body" and slot not in active_body for slot in active):
            raise UnknownPageStateError("HERO'S WEB body role was not frozen")

        seek_value = self._seek_value(raw)
        root_modes = set(raw.get("rootClassTokens", []))
        if "last" in active_roles:
            terminal_slots = (
                (layout.last_slot,)
                if layout.last_slot % 2 == 0
                else (layout.good_slot, layout.last_slot)
            )
            if (
                seek_value != layout.seek_min
                or "mode-last-page" not in root_modes
                or active != terminal_slots
                or tuple(self._captured_slots) != layout.body_slots
            ):
                raise UnknownPageStateError("HERO'S WEB Last screen appeared before completed body coverage")
            self._ended = True
            self._last_state = PageState.END
            self._capture_diagnostics["end"] = {
                "seek_value": seek_value,
                "last_slot": layout.last_slot,
                "captured_body_slots": list(self._captured_slots),
            }
            await self._remove_route_guard(page)
            return PageState.END

        if active_body:
            expected = layout.body_slots[
                len(self._captured_slots) : len(self._captured_slots) + len(active_body)
            ]
            if active_body != expected:
                raise UnknownPageStateError("HERO'S WEB spread has a gap, repeat, or wrong page order")
            offset = layout.body_slots.index(active_body[0])
            expected_seek = layout.seek_max if offset == 0 else layout.seek_max - (offset + 1)
            if offset > 0 and offset % 2 == 0:
                raise UnknownPageStateError("HERO'S WEB spread begins on an unobserved page parity")
            if seek_value != expected_seek:
                raise UnknownPageStateError("HERO'S WEB seek value disagrees with active body position")
            allowed_special: set[str] = set()
            if offset == 0 and "lead_pr" in active_roles:
                allowed_special.add("lead_pr")
                if "mode-first-page" not in root_modes or "mode-top-pr-page" not in root_modes:
                    raise UnknownPageStateError("HERO'S WEB first spread lacks its observed lead flags")
            if active_body[-1] == layout.body_slots[-1] and "ci" in active_roles:
                allowed_special.add("ci")
            if active_roles - {"body"} - allowed_special:
                raise UnknownPageStateError("HERO'S WEB interstitial overlaps an unsupported body spread")
            if not self._observation_is_ready(raw, layout):
                self._last_state = PageState.LOADING
                return PageState.LOADING
            self._last_state = PageState.CONTENT
            return PageState.CONTENT

        if not active:
            raise UnknownPageStateError("HERO'S WEB Viewer has no active visible wrapper")
        if active_roles.issubset({"ci", "pr", "good"}) and active_roles:
            if tuple(self._captured_slots) != layout.body_slots:
                raise UnknownPageStateError(
                    "HERO'S WEB interstitial appeared before every body page was captured"
                )
            if "mode-pr-page" not in root_modes:
                raise UnknownPageStateError("HERO'S WEB interstitial lacks its observed root marker")
            self._last_state = PageState.AD
            return PageState.AD
        raise UnknownPageStateError("HERO'S WEB active page role is unknown")

    async def get_content_context(self, page: Page) -> ContentContext:
        del page
        if (
            self._work_id is None
            or self._episode_id is None
            or self._free_proof is None
        ):
            raise UnknownPageStateError("HERO'S WEB capture context lacks direct access identity proof")
        return ContentContext(
            content_id=f"herosweb:{self._work_id}:{self._episode_id}",
            work_id=self._work_id,
            episode_id=self._episode_id,
            title=self.get_output_metadata()["title"],
        )

    async def get_content_identity(self, page: Page) -> ContentIdentity:
        raw = await self._wait_for_stable_observation(
            page, expected_seek=None, timeout_seconds=MAX_VIEWER_SETTLE_SECONDS,
            require_ready=True,
        )
        self._assert_frozen_layout(raw)
        if self._last_state is not PageState.CONTENT:
            raise UnknownPageStateError("HERO'S WEB identity requested outside body content")
        active = self._active_body_slots(raw)
        if not active:
            raise UnknownPageStateError("HERO'S WEB spread has no body identity")
        offset = len(self._captured_slots)
        if tuple(active) != self._layout.body_slots[offset : offset + len(active)]:
            raise UnknownPageStateError("HERO'S WEB content identity would skip or repeat a body slot")
        return ContentIdentity(
            page_id=self._episode_id,
            page_number=offset + 1,
            source_id="body-slots:" + ",".join(str(slot) for slot in active),
        )

    async def capture_page(self, page: Page) -> tuple[CaptureResult, ...] | None:
        layout = self._layout
        if layout is None or self._last_state is not PageState.CONTENT:
            raise UnknownPageStateError("HERO'S WEB capture started outside a ready body state")
        before = await self._wait_for_stable_observation(
            page, expected_seek=None, timeout_seconds=MAX_VIEWER_SETTLE_SECONDS,
            require_ready=True,
        )
        self._assert_frozen_layout(before)
        active = self._active_body_slots(before)
        offset = len(self._captured_slots)
        expected = layout.body_slots[offset : offset + len(active)]
        if not active or active != expected or len(active) > 2:
            raise UnknownPageStateError("HERO'S WEB capture would skip or combine unknown body pages")

        self._raise_if_route_guard_failed()
        await self._validate_episode_entry(page)
        self._raise_if_route_guard_failed()
        native_outputs, native_raw = await self._materialize_native_targets(page, before, active)

        captures: list[CaptureResult] = []
        capture_modes: list[str] = []
        capture_details: list[dict[str, object]] = []
        materialized_records = {
            record.get("slot"): record
            for record in native_raw.get("records", [])
            if isinstance(record, dict)
        } if isinstance(native_raw, dict) else {}
        for slot, native_output in zip(active, native_outputs, strict=True):
            locator = page.locator(".-cv-pages > .-cv-page").nth(slot).locator("canvas")
            if await locator.count() != 1:
                raise UnknownPageStateError("HERO'S WEB active body slot does not own one canvas")
            canvas = before["wrappers"][slot]["canvases"][0]
            native_proof: dict[str, object] | None = None
            if native_output is not None:
                capture = native_output.capture
                mode = native_output.mode
                native_proof = native_output.proof
            else:
                capture, mode = await self._capture_body_canvas(locator)
            if mode == "rendered_canvas_png" and (
                capture.width != canvas.get("width") or capture.height != canvas.get("height")
            ):
                raise UnknownPageStateError("HERO'S WEB canvas PNG dimensions changed during capture")
            captures.append(capture)
            capture_modes.append(mode)
            capture_details.append(
                {
                    "slot": slot,
                    "format": capture.mime_type,
                    "width": capture.width,
                    "height": capture.height,
                    "mode": mode,
                    "draw_epoch": canvas.get("drawEpoch"),
                    "target_generation": canvas.get("generation"),
                    "canvas_node_id": canvas.get("nodeId"),
                    "native_pixels_proven": native_proof is not None,
                    "original_bytes_proven": False,
                    "native_proof": native_proof,
                    "native_fallback_reason": self._native_fallback_reason(
                        native_raw,
                        materialized_records.get(slot),
                        spread_incomplete=(len(active) > 1 and native_output is None),
                        validation_rejected=(
                            native_output is None
                            and materialized_records.get(slot, {}).get("supported") is True
                        ),
                    ),
                }
            )

        self._raise_if_route_guard_failed()
        after = await self._read_viewer_snapshot(page)
        self._assert_frozen_layout(after)
        fully_verified_native_group = bool(capture_details) and all(
            detail.get("native_pixels_proven") is True
            and detail.get("mode")
            in {"source_canvas_lossless_vp8l", "source_canvas_native_png"}
            for detail in capture_details
        )
        signature = self._capture_observation_signature(
            before, fully_verified_native_group=fully_verified_native_group
        )
        after_signature = self._capture_observation_signature(
            after, fully_verified_native_group=fully_verified_native_group
        )
        if signature != after_signature:
            raise UnknownPageStateError("HERO'S WEB body canvas changed while capture bytes were materialized")
        if page.url != self._target_url:
            raise UnknownPageStateError("HERO'S WEB episode changed while capture bytes were materialized")
        await self._validate_episode_entry(page)
        self._raise_if_route_guard_failed()
        self._captured_slots.extend(active)
        self._last_capture = {
            "slots": list(active),
            "seek_value": self._seek_value(before),
            "modes": capture_modes,
        }
        pages = self._capture_diagnostics.get("pages")
        if isinstance(pages, list):
            pages.append(
                {
                    "slots": list(active),
                    "seek_value": self._seek_value(before),
                    "images": capture_details,
                }
            )
            all_images = [
                image
                for captured_page in pages
                if isinstance(captured_page, dict)
                for image in captured_page.get("images", [])
                if isinstance(image, dict)
            ]
            native_count = sum(image.get("native_pixels_proven") is True for image in all_images)
            self._capture_diagnostics.update(
                {
                    "native_pixels_proven": native_count > 0,
                    "source_native_proven": bool(all_images) and native_count == len(all_images),
                    "original_bytes_proven": False,
                    "mode": (
                        next(iter({image.get("mode") for image in all_images}))
                        if len({image.get("mode") for image in all_images}) == 1
                        else "mixed_canvas_capture"
                    ),
                }
            )
        return tuple(captures)

    @staticmethod
    def _native_fallback_reason(
        raw: object,
        record: dict[str, object] | None,
        *,
        spread_incomplete: bool,
        validation_rejected: bool,
    ) -> str | None:
        if validation_rejected:
            return "native_proof_validation_rejected"
        if not spread_incomplete and record is not None and record.get("supported") is True:
            return None
        if spread_incomplete:
            return "spread_candidate_incomplete_or_unverified"
        if isinstance(raw, dict):
            reason = raw.get("reason")
            if isinstance(reason, str) and re.fullmatch(r"[a-z0-9_]{1,64}", reason):
                return reason
            status = raw.get("status")
            if isinstance(status, str) and status != "ok":
                return f"materialization_{status}"
            if raw.get("observerDrawsChanged") is True:
                return "observer_drew_during_materialization"
        if record is not None:
            reason = record.get("reason")
            if isinstance(reason, str) and re.fullmatch(r"[a-z0-9_]{1,64}", reason):
                return reason
        return "native_source_unavailable_or_unverified"

    async def _materialize_native_targets(
        self,
        page: Page,
        before: dict[str, object],
        active_slots: tuple[int, ...],
    ):
        seek = before.get("seek")
        if (
            not isinstance(seek, list)
            or len(seek) != 1
            or not isinstance(seek[0], dict)
            or type(seek[0].get("nodeId")) is not int
        ):
            raise UnknownPageStateError("HERO'S WEB native capture has no exact seek identity")
        wrappers = before.get("wrappers")
        if not isinstance(wrappers, list):
            raise UnknownPageStateError("HERO'S WEB native capture has no frozen wrapper list")
        if self._layout is None:
            raise UnknownPageStateError("HERO'S WEB native capture has no frozen layout")
        seek_value = self._seek_value(before)
        pair_start = ((self._layout.seek_max - seek_value) // self._layout.seek_step) * 2
        pair_slots = list(range(pair_start, min(pair_start + 2, len(self._layout.roles))))
        expected_targets: list[dict[str, object]] = []
        for slot in active_slots:
            try:
                canvases = wrappers[slot]["canvases"]
                canvas = canvases[0]
                target = {
                    "slot": slot,
                    "seekValue": seek_value,
                    "nodeId": canvas["nodeId"],
                    "width": canvas["width"],
                    "height": canvas["height"],
                    "drawEpoch": canvas["drawEpoch"],
                    "generation": canvas["generation"],
                    "wrapperNodeId": wrappers[slot]["nodeId"],
                    "rootNodeId": self._layout.root_node_id,
                    "pagesWrapNodeId": self._layout.pages_wrap_node_id,
                    "pagesRootNodeId": self._layout.pages_root_node_id,
                    "seekNodeId": self._layout.seek_node_id,
                    "seekMax": self._layout.seek_max,
                    "pairStart": pair_start,
                    "pairSlots": pair_slots,
                    "rootStructuralModes": list(self._layout.root_structural_modes),
                }
            except (IndexError, KeyError, TypeError) as exc:
                raise UnknownPageStateError(
                    "HERO'S WEB native capture target is not in its frozen observation"
                ) from exc
            if (
                any(
                    type(target.get(field)) is not int
                    for field in (
                    "slot",
                    "seekValue",
                    "nodeId",
                    "width",
                    "height",
                    "drawEpoch",
                    "generation",
                    "wrapperNodeId",
                    "rootNodeId",
                    "pagesWrapNodeId",
                    "pagesRootNodeId",
                    "seekNodeId",
                    "seekMax",
                    "pairStart",
                    )
                )
                or not isinstance(target.get("pairSlots"), list)
                or not all(type(value) is int for value in target["pairSlots"])
                or not isinstance(target.get("rootStructuralModes"), list)
                or not all(isinstance(value, str) for value in target["rootStructuralModes"])
            ):
                raise UnknownPageStateError("HERO'S WEB native capture target identity is malformed")
            expected_targets.append(target)
        request = {
            "expectedUrl": self._target_url,
            "episodeId": self._episode_id,
            "workId": self._work_id,
            "seekNodeId": seek[0]["nodeId"],
            "seekValue": self._seek_value(before),
            "layout": {
                "episodeId": self._episode_id,
                "workPath": f"/series/{self._work_id}",
                "url": self._target_url,
                "canonical": [self._target_url],
                "rootNodeId": self._layout.root_node_id,
                "pagesWrapNodeId": self._layout.pages_wrap_node_id,
                "pagesRootNodeId": self._layout.pages_root_node_id,
                "wrapperNodeIds": list(self._layout.wrapper_node_ids),
                "roles": list(self._layout.roles),
                "bodySlots": list(self._layout.body_slots),
                "ciSlot": self._layout.ci_slot,
                "prSlots": list(self._layout.pr_slots),
                "goodSlot": self._layout.good_slot,
                "lastSlot": self._layout.last_slot,
                "seekNodeId": self._layout.seek_node_id,
                "seekMin": self._layout.seek_min,
                "seekMax": self._layout.seek_max,
                "seekStep": self._layout.seek_step,
                "rootStructuralModes": list(self._layout.root_structural_modes),
            },
            "targets": expected_targets,
        }
        raw: object = {"status": "unsupported", "reason": "observer_unavailable"}
        try:
            self._raise_if_route_guard_failed()
            raw = await asyncio.wait_for(
                page.evaluate(
                    """async request => {
                      const observer = window.__hwebCaptureObserver;
                      if (!observer || typeof observer.materializeNativeTargets !== 'function')
                        return {status:'unsupported',reason:'observer_unavailable'};
                      return await observer.materializeNativeTargets(request);
                    }""",
                    request,
                ),
                timeout=15.0,
            )
            self._raise_if_route_guard_failed()
            candidates = decode_native_candidates(raw, expected_targets=expected_targets)
            return encode_native_candidates(candidates), raw
        except TimeoutError:
            self._raise_if_route_guard_failed()
            await self._validate_episode_entry(page)
            return tuple(None for _ in expected_targets), {
                "status": "unsupported",
                "reason": "native_materialization_timeout",
            }
        except PlaywrightError:
            self._raise_if_route_guard_failed()
            await self._validate_episode_entry(page)
            return tuple(None for _ in expected_targets), {
                "status": "unsupported",
                "reason": "native_materialization_error",
            }
        finally:
            try:
                await page.evaluate(
                    """slots => {
                      const observer = window.__hwebCaptureObserver;
                      if (observer && typeof observer.releaseNativeTargets === 'function')
                        observer.releaseNativeTargets(slots);
                    }""",
                    expected_targets,
                )
            except PlaywrightError:
                pass

    async def _capture_body_canvas(self, locator) -> tuple[CaptureResult, str]:
        try:
            data_url = await asyncio.wait_for(
                locator.evaluate("canvas => canvas.toDataURL('image/png')"), timeout=8.0
            )
            if isinstance(data_url, str) and data_url.startswith("data:image/png;base64,"):
                data = base64.b64decode(data_url.partition(",")[2], validate=True)
                return capture_png_bytes(data), "rendered_canvas_png"
        except (PlaywrightError, TimeoutError, ValueError, TypeError):
            pass
        try:
            data = await asyncio.wait_for(
                locator.screenshot(animations="disabled"), timeout=8.0
            )
            return capture_png_bytes(data), "canvas_locator_screenshot_png"
        except (PlaywrightError, TimeoutError, ValueError) as exc:
            raise UnknownPageStateError("HERO'S WEB body canvas could not be captured safely") from exc

    async def get_capture_targets(self, page: Page):
        raw = await self._wait_for_stable_observation(
            page, expected_seek=None, timeout_seconds=MAX_VIEWER_SETTLE_SECONDS,
            require_ready=True,
        )
        self._assert_frozen_layout(raw)
        active = self._active_body_slots(raw)
        if not active:
            raise UnknownPageStateError("HERO'S WEB screenshot fallback has no active body canvas")
        return tuple(
            page.locator(".-cv-pages > .-cv-page").nth(slot).locator("canvas")
            for slot in active
        )

    async def get_capture_target(self, page: Page):
        targets = await self.get_capture_targets(page)
        if not targets:
            raise UnknownPageStateError("HERO'S WEB has no body canvas capture target")
        return targets[0]

    async def go_next(self, page: Page) -> None:
        layout = self._layout
        raw = self._last_observation
        if layout is None or raw is None:
            raise UnknownPageStateError("HERO'S WEB has no frozen viewer state to advance")
        if self._last_state not in {PageState.CONTENT, PageState.AD}:
            raise UnknownPageStateError("HERO'S WEB cannot advance from its current state")
        current = self._seek_value(raw)
        active_body = self._active_body_slots(raw)
        if self._last_state is PageState.CONTENT:
            if self._last_capture is None or tuple(self._last_capture.get("slots", [])) != active_body:
                raise UnknownPageStateError("HERO'S WEB cannot advance before the current body is saved")
            if tuple(self._captured_slots) != layout.body_slots[: len(self._captured_slots)]:
                raise UnknownPageStateError("HERO'S WEB captured body order is not contiguous")
        elif active_body:
            raise UnknownPageStateError("HERO'S WEB interstitial still overlaps a body page")
        next_value = current - layout.seek_step
        if next_value < layout.seek_min:
            raise UnknownPageStateError("HERO'S WEB public seek reached its lower bound unexpectedly")
        self._prior_observation_signature = self._observation_signature(raw)
        self._expected_seek_after_turn = next_value
        first_slot = (layout.seek_max - next_value) // layout.seek_step * 2
        self._expected_slots_after_turn = tuple(
            range(first_slot, min(first_slot + 2, len(layout.roles)))
        )
        self._last_capture = None
        await self._set_seek_value(page, next_value)

    async def wait_for_change(
        self, page: Page, previous_identity: ContentIdentity | None
    ) -> None:
        del previous_identity
        expected = self._expected_seek_after_turn
        expected_slots = self._expected_slots_after_turn
        prior = self._prior_observation_signature
        if expected is None or expected_slots is None or prior is None:
            raise UnknownPageStateError("HERO'S WEB seek transition was not prepared")
        deadline = asyncio.get_running_loop().time() + PAGE_CHANGE_TIMEOUT_MS / 1_000
        previous: tuple[object, ...] | None = None
        while asyncio.get_running_loop().time() < deadline:
            self._raise_if_route_guard_failed()
            if page.url != self._target_url:
                raise UnknownPageStateError("HERO'S WEB seek transition changed episode route")
            raw = await self._read_viewer_snapshot(page)
            self._assert_frozen_layout(raw)
            if self._seek_value(raw) != expected:
                previous = None
                await page.wait_for_timeout(POLL_INTERVAL_MS)
                continue
            active_slots = self._active_slots(raw)
            if not active_slots or any(slot not in expected_slots for slot in active_slots):
                previous = None
                await page.wait_for_timeout(POLL_INTERVAL_MS)
                continue
            active_body = self._active_body_slots(raw)
            if len(self._captured_slots) < len(self._layout.body_slots):
                remaining = self._layout.body_slots[len(self._captured_slots) :]
                if (
                    not active_body
                    or active_body != remaining[: len(active_body)]
                    or len(active_body) > 2
                ):
                    previous = None
                    await page.wait_for_timeout(POLL_INTERVAL_MS)
                    continue
            elif active_body:
                previous = None
                await page.wait_for_timeout(POLL_INTERVAL_MS)
                continue
            signature = self._observation_signature(raw)
            if signature == prior:
                previous = None
                await page.wait_for_timeout(POLL_INTERVAL_MS)
                continue
            ready = self._observation_is_ready(raw, self._layout)
            if previous == signature and ready:
                self._last_observation = raw
                self._expected_seek_after_turn = None
                self._expected_slots_after_turn = None
                self._prior_observation_signature = None
                return
            previous = signature if ready else None
            await page.wait_for_timeout(POLL_INTERVAL_MS)
        raise PageChangeTimeoutError("HERO'S WEB public seek did not settle before its timeout")

    async def _read_viewer_snapshot(self, page: Page) -> dict[str, object]:
        try:
            raw = await asyncio.wait_for(page.evaluate(_VIEWER_SNAPSHOT_SCRIPT), timeout=5.0)
        except (PlaywrightError, TimeoutError) as exc:
            raise UnknownPageStateError("HERO'S WEB Viewer snapshot could not be read") from exc
        if not isinstance(raw, dict):
            raise UnknownPageStateError("HERO'S WEB Viewer snapshot is not structured")
        return raw

    async def collect_debug_metadata(self, page: Page) -> dict[str, object]:
        del page
        result = {
            "site": "herosweb",
            "work_id": self._work_id,
            "episode_id": self._episode_id,
            "free_proof": self._free_proof,
            "viewer": {
                "wrapper_count": len(self._layout.roles) if self._layout else None,
                "body_slot_count": len(self._layout.body_slots) if self._layout else None,
                "captured_body_count": len(self._captured_slots),
                "captured_body_slots": list(self._captured_slots),
            },
            "capture": dict(self._capture_diagnostics),
            "blocked_first_party_telemetry_count": (
                len(self._route_guard.blocked_telemetry) if self._route_guard else 0
            ),
            "blocked_current_episode_read_completed_count": (
                len(self._route_guard.blocked_read_completed)
                if self._route_guard
                else 0
            ),
            "blocked_current_episode_read_completed_paths": (
                list(self._route_guard.blocked_read_completed)
                if self._route_guard
                else []
            ),
            "blocked_external_writes": {
                "count": len(self._blocked_external_writes),
                "host_paths": sorted(set(self._blocked_external_writes)),
            },
            "main_document_route": {
                "interception_count": (
                    len(self._route_guard.main_frame_navigation_urls)
                    if self._route_guard
                    else 0
                ),
                "last_url": (
                    self._safe_navigation_identity(
                        self._route_guard.main_frame_navigation_urls[-1]
                    )
                    if self._route_guard and self._route_guard.main_frame_navigation_urls
                    else None
                ),
                "response_status": (
                    self._route_guard.last_main_frame_response_status
                    if self._route_guard
                    else None
                ),
                "navigation_violation": (
                    self._route_guard.navigation_violation
                    if self._route_guard
                    else None
                ),
                "navigation_frame_role": (
                    self._route_guard.navigation_frame_role
                    if self._route_guard
                    else None
                ),
                "error_category": (
                    self._route_guard.main_frame_error_category
                    if self._route_guard
                    else None
                ),
                "current_page_service_worker_controlled": self._service_worker_controlled,
            },
        }
        if self._route_guard is not None and self._route_guard.unexpected_write is not None:
            result["blocked_unexpected_write_path"] = self._route_guard.unexpected_write
        return copy.deepcopy(result)

    @staticmethod
    def _safe_navigation_identity(url: str) -> str | None:
        try:
            parsed = urlsplit(url)
        except ValueError:
            return None
        if parsed.scheme != "https" or parsed.hostname != "heros-web.com":
            return None
        return f"https://{parsed.hostname}{parsed.path}"

    def get_output_metadata(self) -> dict[str, str | None]:
        title = None
        if self._work_title and self._episode_title:
            title = f"{self._work_title} — {self._episode_title}"
        elif self._episode_title:
            title = self._episode_title
        order = str(self._episode_position) if self._episode_position else None
        return {"title": title, "order": order, "genre": "漫画"}

    async def _remove_route_guard(self, page: Page) -> None:
        guard, self._route_guard = self._route_guard, None
        if guard is None:
            return
        try:
            await page.unroute("**/*", guard)
        except PlaywrightError:
            pass


__all__ = ["HeroswebAdapter", "HeroswebEpisodeRouteGuard"]
