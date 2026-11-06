"""Bounded capture of the observed Yanmaga viewer's pre-JPEG page pixels.

The normal viewer's generated JPEG Blobs are used only as an exact identity
bridge from a visible image back to the canvas pixels copied immediately
before the viewer's own JPEG encoding. They are never saved as original page
images.
"""

from __future__ import annotations

import base64
import binascii
import io
from dataclasses import dataclass

from PIL import Image, UnidentifiedImageError, features
from playwright.async_api import Error as PlaywrightError
from playwright.async_api import Page

from screenshot_crawler.core.capture import CaptureResult

PAGE_WIDTH = 1125
PAGE_HEIGHT = 1600
PAGE_PIXELS = PAGE_WIDTH * PAGE_HEIGHT
MAX_SEGMENT_BYTES = 1_048_576
MAX_TRANSFER_PNG_BYTES = 24 * 1024 * 1024
MAX_CAPTURE_PIXELS = 256 * 1024 * 1024
MAX_CAPTURE_ENCODED_BYTES = 32 * 1024 * 1024
MAX_CAPTURE_CANDIDATES = 192
MAX_BLOB_READ_TASKS = 48
SOURCE_READY_TIMEOUT_MS = 750

_PNG_DATA_URL_PREFIX = "data:image/png;base64,"
_MAX_PNG_DATA_URL_CHARS = len(_PNG_DATA_URL_PREFIX) + 4 * (
    (MAX_TRANSFER_PNG_BYTES + 2) // 3
)


@dataclass(frozen=True, slots=True)
class NativeCaptureOutcome:
    """A proven lossless page capture or a safe, fixed fallback reason."""

    capture: CaptureResult | None
    reason: str
    proof_token: int | None = None


_OBSERVER_SCRIPT = r"""(() => {
  let currentUrl;
  try { currentUrl = new URL(location.href); } catch { return; }
  if (window.top !== window || !currentUrl || currentUrl.origin !== 'https://yanmaga.jp' ||
      currentUrl.username !== '' || currentUrl.password !== '' || currentUrl.hash !== '') return;
  if (!/^\/viewer\/comics\/[^/]+\/[0-9a-f]{32}$/.test(location.pathname) ||
      (location.search !== '' && !/^\?cid=[A-Za-z0-9]{20}$/.test(location.search))) return;
  install();

  function install() {
  const key = '__yanmagaNativeCaptureV1';
  if (window[key]?.version === 1) {
    window[key].activate();
    return;
  }
  const pixelLimit = 256 * 1024 * 1024;
  const encodedLimit = 32 * 1024 * 1024;
  const candidateLimit = 48;
  const totalCandidateLimit = 192;
  const urlBindingLimit = 192;
  const segmentByteLimit = 1024 * 1024;
  const readTaskLimit = 48;
  const alphabet = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/';
  const decodeTable = new Int16Array(128);
  decodeTable.fill(-1);
  for (let i=0;i<alphabet.length;i++) decodeTable[alphabet.charCodeAt(i)] = i;

  const state = {
    version: 1,
    active: false,
    disposed: false,
    overflow: false,
    overflowReason: null,
    hookConflict: false,
    candidates: [],
    boundCandidates: new Set(),
    seenPayloads: new Map(),
    byUrl: new Map(),
    blobCandidates: new WeakMap(),
    invalidBlobs: new WeakSet(),
    sequence: 0,
    totalCandidates: 0,
    captureSequence: 0,
    maxPixelBytes: pixelLimit,
    storedPixelBytes: 0,
    storedEncodedBytes: 0,
    inFlight: 0,
    lastCaptures: new Map(),
    stats: {canvasCopies:0, exactBlobBindings:0, ambiguities:0, misses:0, readFailures:0},
    originalCanvasDescriptor: null,
    originalUrlDescriptor: null,
    originalBlobDescriptor: null,
    wrappedCanvas: null,
    wrappedUrl: null,
    wrappedBlob: null,
    cleanupTimer: null,
    activate,
    pause,
    dispose
  };

  try {
    Object.defineProperty(window, key, {value:state, configurable:true});
  } catch {
    return;
  }

  function fail(reason) {
    state.overflow = true;
    state.overflowReason = reason;
  }

  function releaseCandidate(candidate) {
    if (!candidate || candidate.released) return;
    candidate.released = true;
    state.boundCandidates.delete(candidate);
    state.storedPixelBytes = Math.max(0, state.storedPixelBytes - candidate.pixels.byteLength);
    candidate.pixels = null;
    candidate.payload = '';
  }

  function equalBytesToBase64(bytes, payload) {
    if (!(bytes instanceof Uint8Array) || typeof payload !== 'string') return false;
    const padding = payload.endsWith('==') ? 2 : payload.endsWith('=') ? 1 : 0;
    const expectedLength = Math.floor(payload.length * 3 / 4) - padding;
    if (expectedLength !== bytes.length) return false;
    let outputIndex = 0, accumulator = 0, bitCount = 0;
    for (let i=0;i<payload.length;i++) {
      const code = payload.charCodeAt(i);
      if (code === 61) break;
      if (code >= decodeTable.length) return false;
      const value = decodeTable[code];
      if (value < 0) return false;
      accumulator = (accumulator << 6) | value;
      bitCount += 6;
      if (bitCount >= 8) {
        bitCount -= 8;
        if (((accumulator >> bitCount) & 255) !== bytes[outputIndex++]) return false;
      }
    }
    return outputIndex === bytes.length;
  }

  function dataUrlBytes(payload) {
    if (typeof payload !== 'string' || payload.length === 0 ||
        payload.length > 4 * ((segmentByteLimit + 2) / 3)) return null;
    const padding = payload.endsWith('==') ? 2 : payload.endsWith('=') ? 1 : 0;
    const expectedLength = Math.floor(payload.length * 3 / 4) - padding;
    if (expectedLength < 1 || expectedLength > segmentByteLimit) return null;
    return expectedLength;
  }

  function candidatePixels(canvas) {
    const width = canvas.width, height = canvas.height;
    if (width !== 1127 || (height !== 536 && height !== 538)) return null;
    const ctx = canvas.getContext('2d');
    if (!ctx || typeof ctx.getImageData !== 'function') return null;
    const attributes = typeof ctx.getContextAttributes === 'function'
      ? ctx.getContextAttributes() : null;
    if (!attributes || attributes.colorSpace !== 'srgb' ||
        (attributes.colorType && !['unorm8','uint8'].includes(attributes.colorType))) return null;
    const image = ctx.getImageData(0, 0, width, height);
    if (!(image.data instanceof Uint8ClampedArray) ||
        (image.colorSpace && image.colorSpace !== 'srgb') ||
        (image.pixelFormat && !['uint8','rgba-unorm8'].includes(image.pixelFormat))) return null;
    const source = image.data;
    const pixels = new Uint8Array(source.length);
    pixels.set(source);
    return {width,height,pixels};
  }

  function firstByteView(parts) {
    if (!Array.isArray(parts) || parts.length !== 1) return null;
    const part = parts[0];
    if (!(part instanceof Uint8Array) || part instanceof Uint8ClampedArray) return null;
    return part;
  }

  function addCanvasCandidate(canvas, result, args, copied) {
    if (!copied || args[0] !== 'image/jpeg' || args[1] !== 0.9 ||
        typeof result !== 'string' || !result.startsWith('data:image/jpeg;base64,')) return;
    const payload = result.slice('data:image/jpeg;base64,'.length);
    const encodedBytes = dataUrlBytes(payload);
    if (encodedBytes === null) return;
    if (state.overflow) return;
    const pixelBytes = copied.pixels.byteLength;
    const encodedChars = payload.length;
    if (state.candidates.length >= candidateLimit ||
        state.totalCandidates >= totalCandidateLimit ||
        state.storedPixelBytes + pixelBytes > pixelLimit ||
        state.storedEncodedBytes + encodedChars > encodedLimit) {
      fail('capture_buffer_overflow');
      return;
    }
    const candidate = {
      sequence: ++state.sequence,
      width: copied.width,
      height: copied.height,
      pixels: copied.pixels,
      payload,
      encodedChars,
      encodedBytes,
      ambiguous: state.seenPayloads.has(payload),
      released: false,
      url: null
    };
    state.seenPayloads.set(payload, candidate.sequence);
    state.candidates.push(candidate);
    state.totalCandidates++;
    state.storedPixelBytes += pixelBytes;
    state.storedEncodedBytes += encodedChars;
    state.stats.canvasCopies++;
  }

  function matchBlobParts(blob, parts, options) {
    if (!(blob instanceof Blob) || String(options?.type || '').toLowerCase() !== 'image/jpeg' ||
        blob.type !== 'image/jpeg' || blob.size < 1 || blob.size > segmentByteLimit) return;
    const bytes = firstByteView(parts);
    if (!bytes || bytes.length !== blob.size) return;
    const candidates = new Set([...state.candidates, ...state.boundCandidates]);
    const matches = [...candidates].filter(candidate =>
      !candidate.released && candidate.encodedBytes === bytes.byteLength &&
      equalBytesToBase64(bytes, candidate.payload));
    if (matches.length === 1 && !matches[0].ambiguous &&
        !state.boundCandidates.has(matches[0])) {
      const candidate = matches[0];
      state.candidates.splice(state.candidates.indexOf(candidate), 1);
      state.boundCandidates.add(candidate);
      state.blobCandidates.set(blob, candidate);
      return;
    }
    if (matches.length > 0) {
      state.stats.ambiguities++;
      for (const candidate of matches) {
        const index = state.candidates.indexOf(candidate);
        if (index >= 0) state.candidates.splice(index, 1);
        for (const [url, bound] of state.byUrl) {
          if (bound === candidate) state.byUrl.delete(url);
        }
        state.boundCandidates.delete(candidate);
        releaseCandidate(candidate);
      }
      state.invalidBlobs.add(blob);
    } else if (state.candidates.length) {
      state.stats.misses++;
    }
  }

  function observeCreatedBlob(blob, url) {
    if (state.invalidBlobs.has(blob)) return;
    const candidate = state.blobCandidates.get(blob);
    if (!candidate || candidate.released) return;
    if (state.inFlight >= readTaskLimit) {
      fail('blob_read_task_overflow');
      releaseCandidate(candidate);
      return;
    }
    state.inFlight++;
    Promise.resolve().then(() => blob.arrayBuffer()).then(buffer => {
      if (state.disposed || candidate.released) return;
      const bytes = new Uint8Array(buffer);
      if (bytes.length !== blob.size || !equalBytesToBase64(bytes, candidate.payload)) {
        state.stats.readFailures++;
        releaseCandidate(candidate);
        return;
      }
      if (state.byUrl.size >= urlBindingLimit) {
        fail('blob_url_binding_overflow');
        releaseCandidate(candidate);
        return;
      }
      candidate.url = url;
      state.byUrl.set(url, candidate);
      state.stats.exactBlobBindings++;
    }).catch(() => {
      state.stats.readFailures++;
      releaseCandidate(candidate);
    }).finally(() => { state.inFlight = Math.max(0, state.inFlight - 1); });
  }

  function activate() {
    if (state.disposed || state.active) return !state.disposed;
    const canvasDescriptor = Object.getOwnPropertyDescriptor(HTMLCanvasElement.prototype, 'toDataURL');
    const urlDescriptor = Object.getOwnPropertyDescriptor(URL, 'createObjectURL');
    const blobDescriptor = Object.getOwnPropertyDescriptor(window, 'Blob');
    if (!canvasDescriptor?.value || !urlDescriptor?.value || !blobDescriptor?.value) {
      state.hookConflict = true;
      return false;
    }
    if (state.originalCanvasDescriptor && canvasDescriptor.value !== state.originalCanvasDescriptor.value) {
      state.hookConflict = true;
      return false;
    }
    if (state.originalUrlDescriptor && urlDescriptor.value !== state.originalUrlDescriptor.value) {
      state.hookConflict = true;
      return false;
    }
    if (state.originalBlobDescriptor && blobDescriptor.value !== state.originalBlobDescriptor.value) {
      state.hookConflict = true;
      return false;
    }
    state.originalCanvasDescriptor ||= canvasDescriptor;
    state.originalUrlDescriptor ||= urlDescriptor;
    state.originalBlobDescriptor ||= blobDescriptor;
    const originalToDataURL = canvasDescriptor.value;
    const originalCreateObjectURL = urlDescriptor.value;
    const NativeBlob = blobDescriptor.value;

    state.wrappedCanvas = function(...args) {
      let copied = null;
      const expectedCall = args[0] === 'image/jpeg' && args[1] === 0.9 &&
        state.active && !state.overflow;
      if (expectedCall && this.width === 1127 &&
          (this.height === 536 || this.height === 538)) {
        const nextPixelBytes = this.width * this.height * 4;
        if (state.candidates.length >= candidateLimit ||
            state.totalCandidates >= totalCandidateLimit ||
            state.storedPixelBytes + nextPixelBytes > pixelLimit) {
          fail('capture_buffer_overflow');
        } else {
          try { copied = candidatePixels(this); } catch { /* leave viewer behavior unchanged */ }
        }
      }
      const result = Reflect.apply(originalToDataURL, this, args);
      try { addCanvasCandidate(this, result, args, copied); } catch { /* capture is optional */ }
      return result;
    };
    state.wrappedBlob = new Proxy(NativeBlob, {
      construct(target, args, newTarget) {
        const blob = Reflect.construct(target, args, newTarget === state.wrappedBlob ? target : newTarget);
        try { matchBlobParts(blob, args[0], args[1]); } catch { /* capture is optional */ }
        return blob;
      }
    });
    state.wrappedUrl = function(...args) {
      const url = Reflect.apply(originalCreateObjectURL, this, args);
      try { observeCreatedBlob(args[0], url); } catch { /* capture is optional */ }
      return url;
    };
    try {
      Object.defineProperty(HTMLCanvasElement.prototype, 'toDataURL', {
        ...canvasDescriptor, value:state.wrappedCanvas
      });
      Object.defineProperty(window, 'Blob', {...blobDescriptor, value:state.wrappedBlob});
      Object.defineProperty(URL, 'createObjectURL', {...urlDescriptor, value:state.wrappedUrl});
    } catch {
      state.hookConflict = true;
      restoreOwnedHooks();
      return false;
    }
    state.active = true;
    if (state.cleanupTimer !== null) clearTimeout(state.cleanupTimer);
    state.cleanupTimer = setTimeout(dispose, 10 * 60 * 1000);
    return true;
  }

  function restoreOwnedHooks() {
    if (state.wrappedCanvas && HTMLCanvasElement.prototype.toDataURL === state.wrappedCanvas &&
        state.originalCanvasDescriptor) {
      Object.defineProperty(HTMLCanvasElement.prototype, 'toDataURL', state.originalCanvasDescriptor);
    }
    if (state.wrappedUrl && URL.createObjectURL === state.wrappedUrl && state.originalUrlDescriptor) {
      Object.defineProperty(URL, 'createObjectURL', state.originalUrlDescriptor);
    }
    if (state.wrappedBlob && window.Blob === state.wrappedBlob && state.originalBlobDescriptor) {
      Object.defineProperty(window, 'Blob', state.originalBlobDescriptor);
    }
    state.active = false;
  }

  function pause() {
    restoreOwnedHooks();
  }

  function dispose() {
    if (state.disposed) return;
    restoreOwnedHooks();
    state.disposed = true;
    if (state.cleanupTimer !== null) clearTimeout(state.cleanupTimer);
    state.cleanupTimer = null;
    for (const candidate of state.candidates) releaseCandidate(candidate);
    state.candidates.length = 0;
    for (const candidate of state.byUrl.values()) releaseCandidate(candidate);
    for (const candidate of state.boundCandidates) releaseCandidate(candidate);
    state.boundCandidates.clear();
    state.byUrl.clear();
    state.seenPayloads.clear();
    state.lastCaptures.clear();
    state.storedPixelBytes = 0;
    state.storedEncodedBytes = 0;
    if (window[key] === state) {
      try { delete window[key]; } catch {}
    }
  }
  activate();
  }
})();"""


_CAPTURE_PAGE_SCRIPT = r"""async args => {
  const {pageId,waitMs}=args;
  const state = window.__yanmagaNativeCaptureV1;
  const fail = reason => ({ok:false,reason});
  if (!state || state.version !== 1 || state.disposed) return fail('observer_unavailable');
  if (state.hookConflict) return fail('hook_conflict');
  if (state.overflow) return fail(state.overflowReason || 'capture_buffer_overflow');
  const rootNodes = [...document.querySelectorAll('.pages#content')];
  const wrapperNodes = [...document.querySelectorAll('#'+CSS.escape(pageId))];
  if (rootNodes.length !== 1 || wrapperNodes.length !== 1 ||
      wrapperNodes[0].parentElement !== rootNodes[0]) return fail('unsupported_page_structure');
  const root = rootNodes[0], wrapper = wrapperNodes[0];
  const purePageTranslation = node => {
    if (node !== wrapper) return getComputedStyle(node).transform === 'none';
    const transform = getComputedStyle(node).transform;
    if (transform === 'none') return true;
    try {
      const matrix = new DOMMatrixReadOnly(transform);
      return matrix.is2D && matrix.a === 1 && matrix.b === 0 && matrix.c === 0 &&
        matrix.d === 1 && Number.isFinite(matrix.e) && Number.isFinite(matrix.f) && matrix.f === 0;
    } catch {
      return false;
    }
  };
  const normalStyle = node => {
    const style = getComputedStyle(node);
    return style.opacity === '1' && purePageTranslation(node) && style.filter === 'none' &&
      style.mixBlendMode === 'normal' && style.clipPath === 'none' &&
      (!style.maskImage || style.maskImage === 'none') &&
      style.visibility === 'visible';
  };
  const emptyPseudo = (node,pseudo) => {
    const style=getComputedStyle(node,pseudo);
    return ['none','normal'].includes(style.content) && style.backgroundImage==='none' &&
      style.opacity==='1' && style.filter==='none' && style.transform==='none';
  };
  const emptyHostAfter = (node,pseudo) => {
    if (pseudo !== '::after' || node.parentElement?.className !== 'pt-img' ||
        node.localName !== 'div') return false;
    const style=getComputedStyle(node,pseudo);
    const zero = value => Math.abs(Number.parseFloat(value) || 0) <= 0.001;
    return style.content === '""' && style.display === 'block' &&
      style.position === 'absolute' && style.backgroundColor === 'rgba(0, 0, 0, 0)' &&
      style.backgroundImage === 'none' && style.opacity === '1' &&
      ['none',''].includes(style.borderImageSource) &&
      ['borderTopWidth','borderRightWidth','borderBottomWidth','borderLeftWidth']
        .every(name => zero(style[name])) &&
      ['borderTopStyle','borderRightStyle','borderBottomStyle','borderLeftStyle']
        .every(name => style[name] === 'none') && style.outlineStyle === 'none' &&
      style.boxShadow === 'none' && style.textShadow === 'none' &&
      style.filter === 'none' && style.backdropFilter === 'none' &&
      ['none',''].includes(style.getPropertyValue('-webkit-backdrop-filter')) &&
      style.transform === 'none' &&
      style.mixBlendMode === 'normal' && style.isolation === 'auto' &&
      style.clipPath === 'none' && (!style.maskImage || style.maskImage === 'none') &&
      style.overflowX === 'visible' && style.overflowY === 'visible' &&
      ['paddingTop','paddingRight','paddingBottom','paddingLeft',
        'marginTop','marginRight','marginBottom','marginLeft'].every(name => zero(style[name]));
  };
  for (let node=wrapper;node;node=node.parentElement) {
    if (!normalStyle(node)) return fail('unsupported_compositing_style');
    if (!emptyPseudo(node,'::before') || !emptyPseudo(node,'::after')) {
      return fail('unsupported_pseudo_paint');
    }
    if (node === document.documentElement) break;
  }
  const wrapperStyle = getComputedStyle(wrapper);
  if (!['hidden','clip'].includes(wrapperStyle.overflowX) ||
      !['hidden','clip'].includes(wrapperStyle.overflowY)) return fail('page_clip_unproven');
  const logicalNodes = [...wrapper.children].filter(node =>
    node.localName === 'div' && String(node.className || '') === 'pt-img');
  if (wrapper.children.length !== 1 || logicalNodes.length !== 1) {
    return fail('unsupported_logical_page_container');
  }
  const logicalPage = logicalNodes[0], logicalStyle = getComputedStyle(logicalPage);
  if (!normalStyle(logicalPage) || logicalStyle.position !== 'relative' ||
      logicalStyle.overflowX !== 'visible' || logicalStyle.overflowY !== 'visible' ||
      !emptyPseudo(logicalPage,'::before') || !emptyPseudo(logicalPage,'::after')) {
    return fail('unsupported_logical_page_style');
  }
  const zeroPadding = value => Math.abs(Number.parseFloat(value) || 0) <= 0.001;
  const rightPadding = Number.parseFloat(wrapperStyle.paddingRight);
  const borderNames=['borderLeftWidth','borderRightWidth','borderTopWidth','borderBottomWidth'];
  if (!zeroPadding(wrapperStyle.paddingLeft) || !zeroPadding(wrapperStyle.paddingTop) ||
      !zeroPadding(wrapperStyle.paddingBottom) ||
      ![0,2].some(value => Math.abs(rightPadding-value) <= 0.001) ||
      borderNames.some(name => !zeroPadding(wrapperStyle[name]))) {
    return fail('unsupported_page_gutter');
  }
  const outerBox = wrapper.getBoundingClientRect();
  const box = logicalPage.getBoundingClientRect();
  if (Math.abs(box.x-outerBox.x) > 0.03 || Math.abs(box.y-outerBox.y) > 0.03 ||
      Math.abs(outerBox.width-box.width-rightPadding) > 0.03 ||
      Math.abs(outerBox.height-box.height) > 0.03) return fail('unsupported_logical_page_geometry');
  const scaleX = box.width / 1125, scaleY = box.height / 1600;
  if (!Number.isFinite(scaleX) || !Number.isFinite(scaleY) ||
      Math.abs(scaleX-1.125) > 0.001 || Math.abs(scaleY-1.125) > 0.001 ||
      Math.abs(scaleX-scaleY) > 0.0001) return fail('unsupported_native_geometry');
  const segmentHosts = [...logicalPage.children];
  const images = segmentHosts.map(host => host.children.length === 1 ? host.children[0] : null);
  if (segmentHosts.length !== 3 || images.some(image => !image || image.localName !== 'img') ||
      wrapper.querySelectorAll('img').length !== 3) {
    return fail('segment_count_mismatch');
  }
  const expected = [
    {width:1127,height:536,top:0},
    {width:1127,height:536,top:532},
    {width:1127,height:538,top:1064}
  ];
  for (let i=0;i<images.length;i++) {
    const host=segmentHosts[i], hostStyle=getComputedStyle(host), hostBox=host.getBoundingClientRect();
    const image = images[i], wanted=expected[i], style=getComputedStyle(image), imageBox=image.getBoundingClientRect();
    if (!normalStyle(host) || !normalStyle(image) ||
        !emptyPseudo(host,'::before') || !emptyHostAfter(host,'::after')) {
      return fail('unsupported_compositing_style');
    }
    if (hostStyle.position !== 'absolute' || hostStyle.zIndex !== 'auto' ||
        hostStyle.overflowX !== 'hidden' || hostStyle.overflowY !== 'hidden' ||
        style.position !== 'absolute' || style.zIndex !== 'auto' ||
        style.overflowX !== 'clip' || style.overflowY !== 'clip') {
      return fail('unsupported_painter_order');
    }
    if (!image.complete || image.naturalWidth !== wanted.width || image.naturalHeight !== wanted.height ||
        style.objectFit !== 'fill' || style.objectPosition !== '50% 50%' ||
        Math.abs(hostBox.x-box.x) > 0.03 ||
        Math.abs(hostBox.y-(box.y+wanted.top*scaleY)) > 0.03 ||
        Math.abs(hostBox.width-wanted.width*scaleX) > 0.03 ||
        Math.abs(hostBox.height-wanted.height*scaleY) > 0.03 ||
        Math.abs(imageBox.x-hostBox.x) > 0.03 ||
        Math.abs(imageBox.y-hostBox.y) > 0.03 ||
        Math.abs(imageBox.width-hostBox.width) > 0.03 ||
        Math.abs(imageBox.height-hostBox.height) > 0.03) {
      return fail('unsupported_segment_geometry_or_style');
    }
  }
  const styleProof = (node,pseudo='') => {
    const style=getComputedStyle(node,pseudo), values=[];
    for (let i=0;i<style.length;i++) {
      const name=style[i];
      values.push([name,style.getPropertyValue(name)]);
    }
    values.sort((left,right)=>left[0].localeCompare(right[0]));
    return values;
  };
  const rectProof = node => {
    const rect=node.getBoundingClientRect();
    return [rect.x,rect.y,rect.width,rect.height];
  };
  const proofSignature = () => {
    const currentRoots=[...document.querySelectorAll('.pages#content')];
    const currentWrappers=[...document.querySelectorAll('#'+CSS.escape(pageId))];
    if (currentRoots.length!==1 || currentWrappers.length!==1) return null;
    const currentRoot=currentRoots[0], currentWrapper=currentWrappers[0], chain=[];
    for (let node=currentWrapper;node;node=node.parentElement) {
      chain.push({
        element:[node.localName,node.id,String(node.className || '')],
        rect:rectProof(node),
        style:styleProof(node),
        before:styleProof(node,'::before'),
        after:styleProof(node,'::after')
      });
      if (node===document.documentElement) break;
    }
    const currentLogicalPages=[...currentWrapper.children].filter(node =>
      node.localName==='div' && String(node.className || '')==='pt-img');
    const currentLogical=currentLogicalPages.length===1?currentLogicalPages[0]:null;
    const currentHosts=currentLogical?[...currentLogical.children]:[];
    const currentImages=currentHosts.map(host=>host.children.length===1?host.children[0]:null);
    return JSON.stringify({
      location:[location.origin,location.pathname,location.search,location.hash],
      rootElement:[currentRoot.localName,currentRoot.id,String(currentRoot.className || '')],
      rootRect:rectProof(currentRoot),
      directParent:currentWrapper.parentElement===currentRoot,
      children:[...currentWrapper.children].map(node=>[node.localName,node.id,String(node.className || '')]),
      chain,
      wrapperOverflow:[getComputedStyle(currentWrapper).overflowX,getComputedStyle(currentWrapper).overflowY],
      logicalPage:currentLogical?{
        element:[currentLogical.localName,currentLogical.id,String(currentLogical.className || '')],
        rect:rectProof(currentLogical),style:styleProof(currentLogical),
        before:styleProof(currentLogical,'::before'),after:styleProof(currentLogical,'::after'),
        hosts:currentHosts.map(host=>({
          element:[host.localName,host.id,String(host.className || '')],rect:rectProof(host),
          style:styleProof(host),before:styleProof(host,'::before'),after:styleProof(host,'::after')
        }))
      }:null,
      images:currentImages.map(image=>image?({
        element:[image.localName,image.id,String(image.className || '')],
        rect:rectProof(image),
        style:styleProof(image),
        complete:image.complete,
        natural:[image.naturalWidth,image.naturalHeight],
        source:image.currentSrc || ''
      }):null)
    });
  };
  const initialProof=proofSignature();
  if (typeof initialProof!=='string') return fail('native_proof_unavailable');
  const deadline = performance.now() + Math.min(2000, Math.max(0, Number(waitMs) || 0));
  let records = null, sources = null;
  while (true) {
    sources = images.map(image => image.currentSrc || '');
    if (sources.some(source => !source.startsWith('blob:'))) return fail('segment_source_not_blob');
    records = sources.map(source => state.byUrl.get(source) || null);
    if (records.every(Boolean)) break;
    if (state.overflow) return fail(state.overflowReason || 'capture_buffer_overflow');
    if (performance.now() >= deadline) return fail('segment_source_not_exactly_bound');
    await new Promise(resolve => setTimeout(resolve, 20));
  }
  if (new Set(sources).size !== 3 || new Set(records.map(record => record.sequence)).size !== 3) {
    return fail('duplicate_segment_source');
  }
  if (proofSignature()!==initialProof) return fail('native_proof_changed_while_waiting');
  for (let index=0;index<records.length;index++) {
    const record=records[index], image=images[index];
    if (record.released || record.width !== expected[index].width ||
        record.height !== expected[index].height || !record.pixels ||
        record.pixels.byteLength !== record.width*record.height*4 ||
        record.url !== sources[index] || image.naturalWidth !== record.width ||
        image.naturalHeight !== record.height) return fail('segment_binding_changed');
    for (let offset=3;offset<record.pixels.length;offset+=4) {
      if (record.pixels[offset] !== 255) return fail('segment_not_opaque');
    }
  }
  const canvas = document.createElement('canvas');
  canvas.width=1125; canvas.height=1600;
  const context = canvas.getContext('2d', {alpha:false,colorSpace:'srgb'});
  const contextAttributes=context?.getContextAttributes?.();
  if (!context || !contextAttributes || contextAttributes.alpha !== false ||
      contextAttributes.colorSpace !== 'srgb' ||
      (contextAttributes.colorType && !['unorm8','uint8'].includes(contextAttributes.colorType))) {
    return fail('native_compositor_unavailable');
  }
  context.globalAlpha=1; context.globalCompositeOperation='source-over'; context.filter='none';
  for (let index=0;index<records.length;index++) {
    const record=records[index];
    const imageData=context.createImageData(record.width,record.height);
    imageData.data.set(record.pixels);
    context.putImageData(imageData,0,expected[index].top);
  }
  const outputPixels=context.getImageData(0,0,1125,1600);
  for (let offset=3;offset<outputPixels.data.length;offset+=4) {
    if (outputPixels.data[offset] !== 255) return fail('composite_contains_transparency');
  }
  if (images.some((image,index) => image.currentSrc !== sources[index] ||
      state.byUrl.get(sources[index]) !== records[index])) return fail('segment_binding_changed');
  if (proofSignature()!==initialProof) return fail('native_proof_changed_during_composition');
  const png = canvas.toDataURL('image/png');
  const expectedToken=++state.captureSequence;
  state.lastCaptures.set(pageId,{
    pageId,token:expectedToken,proof:initialProof,proofSignature,sources:[...sources],records:[...records]
  });
  return {ok:true,token:expectedToken,png};
}"""


_VERIFY_CAPTURE_SCRIPT = r"""args => {
  const {pageId,token}=args;
  const state=window.__yanmagaNativeCaptureV1, last=state?.lastCaptures?.get(pageId);
  if (!state || state.disposed || !last || last.pageId!==pageId || last.token!==token) return false;
  if (typeof last.proofSignature!=='function' || last.proofSignature()!==last.proof) return false;
  const wrapper=document.getElementById(pageId);
  if (!wrapper) return false;
  const images=[...wrapper.querySelectorAll('img')];
  return images.length===3 && images.every((image,index) =>
    image.currentSrc===last.sources[index] && state.byUrl.get(last.sources[index])===last.records[index] &&
    !last.records[index].released);
}"""


_VERIFY_CAPTURE_GROUP_SCRIPT = r"""captures => {
  const state=window.__yanmagaNativeCaptureV1;
  if (!state || state.disposed || !Array.isArray(captures) ||
      captures.length<1 || captures.length>2) return false;
  const ids=captures.map(item=>item?.pageId);
  if (ids.some(id=>typeof id!=='string') || new Set(ids).size!==ids.length) return false;
  return captures.every(item=>{
    if (!Number.isInteger(item.token) || item.token<1) return false;
    const last=state.lastCaptures.get(item.pageId);
    if (!last || last.pageId!==item.pageId || last.token!==item.token ||
        typeof last.proofSignature!=='function' || last.proofSignature()!==last.proof) return false;
    const wrapper=document.getElementById(item.pageId);
    if (!wrapper) return false;
    const images=[...wrapper.querySelectorAll('img')];
    return images.length===3 && images.every((image,index) =>
      image.currentSrc===last.sources[index] &&
      state.byUrl.get(last.sources[index])===last.records[index] &&
      !last.records[index].released);
  });
}"""


_RELEASE_PAGE_SCRIPT = r"""({pageId}) => {
  const state=window.__yanmagaNativeCaptureV1;
  if (!state || state.disposed) return;
  const wrapper=document.getElementById(pageId);
  if (!wrapper) return;
  for (const image of wrapper.querySelectorAll('img')) {
    const source=image.currentSrc || '';
    const record=state.byUrl.get(source);
    if (record) {
      state.byUrl.delete(source);
      if (!record.released) {
        state.storedPixelBytes=Math.max(0,state.storedPixelBytes-record.pixels.byteLength);
        record.pixels=null; record.payload=''; record.released=true;
      }
    }
  }
  state.lastCaptures.delete(pageId);
}"""


_PAUSE_SCRIPT = r"""() => {
  const state=window.__yanmagaNativeCaptureV1;
  if (state && !state.disposed) state.pause();
}"""


_ACTIVATE_SCRIPT = r"""() => {
  const state=window.__yanmagaNativeCaptureV1;
  return !!state && !state.disposed && state.activate();
}"""


_DISPOSE_SCRIPT = r"""() => {
  const state=window.__yanmagaNativeCaptureV1;
  if (state && !state.disposed) state.dispose();
}"""


async def install_yanmaga_native_observer(page: Page) -> None:
    """Install a document-local observer before the adapter's first navigation."""

    await page.add_init_script(_OBSERVER_SCRIPT)


async def capture_yanmaga_native_webp(
    page: Page, page_id: str
) -> NativeCaptureOutcome:
    """Capture one observed logical page as lossless WebP, or explain fallback."""

    try:
        raw = await page.evaluate(
            _CAPTURE_PAGE_SCRIPT,
            {"pageId": page_id, "waitMs": SOURCE_READY_TIMEOUT_MS},
        )
    except (PlaywrightError, TypeError, ValueError):
        return NativeCaptureOutcome(None, "browser_capture_unavailable")
    if not isinstance(raw, dict) or raw.get("ok") is not True:
        reason = raw.get("reason") if isinstance(raw, dict) else None
        return NativeCaptureOutcome(
            None,
            reason if isinstance(reason, str) and reason.isascii() else "native_proof_unavailable",
        )
    token = raw.get("token")
    png_url = raw.get("png")
    if isinstance(token, bool) or not isinstance(token, int) or token < 1:
        return NativeCaptureOutcome(None, "native_capture_token_invalid")
    if (
        not isinstance(png_url, str)
        or not png_url.startswith(_PNG_DATA_URL_PREFIX)
        or len(png_url) > _MAX_PNG_DATA_URL_CHARS
    ):
        return NativeCaptureOutcome(None, "native_png_transfer_invalid")
    try:
        png = base64.b64decode(png_url[len(_PNG_DATA_URL_PREFIX) :], validate=True)
    except (binascii.Error, ValueError):
        return NativeCaptureOutcome(None, "native_png_transfer_invalid")
    if len(png) > MAX_TRANSFER_PNG_BYTES:
        return NativeCaptureOutcome(None, "native_png_transfer_oversized")
    if not await _verify_yanmaga_native_capture(page, page_id, token):
        return NativeCaptureOutcome(None, "native_capture_changed_after_composition")
    try:
        capture = _encode_lossless_webp(png)
    except (OSError, ValueError, UnidentifiedImageError):
        return NativeCaptureOutcome(None, "native_webp_encode_or_roundtrip_failed")
    if not await _verify_yanmaga_native_capture(page, page_id, token):
        return NativeCaptureOutcome(None, "native_capture_changed_during_encoding")
    return NativeCaptureOutcome(
        capture, "native_pre_jpeg_lossless_webp", proof_token=token
    )


def _encode_lossless_webp(png: bytes) -> CaptureResult:
    if not features.check("webp"):
        raise OSError("Pillow WebP support is unavailable")
    if not png or len(png) > MAX_TRANSFER_PNG_BYTES:
        raise ValueError("native PNG transport exceeds its bound")
    with Image.open(io.BytesIO(png)) as decoded_png:
        if (
            decoded_png.format != "PNG"
            or decoded_png.size != (PAGE_WIDTH, PAGE_HEIGHT)
            or getattr(decoded_png, "n_frames", 1) != 1
        ):
            raise ValueError("native PNG format or dimensions are invalid")
        decoded_png.load()
        original = decoded_png.convert("RGBA")
    rgba = original.tobytes()
    if len(rgba) != PAGE_PIXELS * 4 or original.getchannel("A").getextrema() != (255, 255):
        raise ValueError("native page pixels are not fully opaque RGBA")
    output = io.BytesIO()
    original.save(output, format="WEBP", lossless=True, method=4)
    encoded = output.getvalue()
    if not _single_vp8l(encoded, width=PAGE_WIDTH, height=PAGE_HEIGHT):
        raise ValueError("Pillow did not emit one lossless VP8L frame")
    with Image.open(io.BytesIO(encoded)) as decoded_webp:
        if (
            decoded_webp.format != "WEBP"
            or decoded_webp.size != (PAGE_WIDTH, PAGE_HEIGHT)
            or getattr(decoded_webp, "n_frames", 1) != 1
        ):
            raise ValueError("encoded WebP format or dimensions changed")
        decoded_webp.load()
        if decoded_webp.convert("RGBA").tobytes() != rgba:
            raise ValueError("lossless WebP did not preserve exact page pixels")
    return CaptureResult(encoded, PAGE_WIDTH, PAGE_HEIGHT, "image/webp", ".webp")


def _single_vp8l(data: bytes, *, width: int, height: int) -> bool:
    if (
        len(data) < 25
        or data[:4] != b"RIFF"
        or int.from_bytes(data[4:8], "little") != len(data) - 8
        or data[8:12] != b"WEBP"
        or data[12:16] != b"VP8L"
    ):
        return False
    chunk_size = int.from_bytes(data[16:20], "little")
    end = 20 + chunk_size
    if chunk_size < 5 or end + (chunk_size & 1) != len(data) or data[20] != 0x2F:
        return False
    encoded_width = 1 + data[21] + ((data[22] & 0x3F) << 8)
    encoded_height = 1 + (data[22] >> 6) + (data[23] << 2) + ((data[24] & 0x0F) << 10)
    version = data[24] >> 5
    return encoded_width == width and encoded_height == height and version == 0


async def verify_yanmaga_native_capture(page: Page, page_id: str, token: int) -> bool:
    return await _verify_yanmaga_native_capture(page, page_id, token)


async def verify_yanmaga_native_group(
    page: Page, captures: list[tuple[str, int]]
) -> bool:
    """Atomically revalidate all native members of one visible spread."""

    if not captures or len(captures) > 2:
        return False
    try:
        return await page.evaluate(
            _VERIFY_CAPTURE_GROUP_SCRIPT,
            [{"pageId": page_id, "token": token} for page_id, token in captures],
        ) is True
    except (PlaywrightError, TypeError, ValueError):
        return False


async def _verify_yanmaga_native_capture(page: Page, page_id: str, token: int) -> bool:
    try:
        return await page.evaluate(
            _VERIFY_CAPTURE_SCRIPT, {"pageId": page_id, "token": token}
        ) is True
    except (PlaywrightError, TypeError, ValueError):
        return False


async def release_yanmaga_native_page(page: Page, page_id: str) -> None:
    try:
        await page.evaluate(_RELEASE_PAGE_SCRIPT, {"pageId": page_id})
    except (PlaywrightError, TypeError, ValueError):
        return


async def pause_yanmaga_native_observer(page: Page) -> None:
    try:
        await page.evaluate(_PAUSE_SCRIPT)
    except (PlaywrightError, TypeError, ValueError):
        return


async def activate_yanmaga_native_observer(page: Page) -> bool:
    try:
        return await page.evaluate(_ACTIVATE_SCRIPT) is True
    except (PlaywrightError, TypeError, ValueError):
        return False


async def dispose_yanmaga_native_observer(page: Page) -> None:
    try:
        await page.evaluate(_DISPOSE_SCRIPT)
    except (PlaywrightError, TypeError, ValueError):
        return
