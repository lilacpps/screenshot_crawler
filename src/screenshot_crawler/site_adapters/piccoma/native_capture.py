"""Strict Piccoma source-tile replay for the observed horizontal viewer."""

from __future__ import annotations

import asyncio
import base64
import io
import json
import math
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

from PIL import Image, features
from playwright.async_api import Page, Response

from screenshot_crawler.core.capture import CaptureResult

MAX_TARGET_EVENTS = 512
MAX_RETAINED_CANVASES = 16
MAX_TRACE_EVENTS = 20_000
MAX_SOURCE_BYTES = 8_000_000
# A new fail-closed transport ceiling admits 512 bounded target events at
# 16 KiB/event, with a separate 256-node/event traversal guard. Neither bound
# truncates; unusually large full traces are rejected instead.
MAX_NATIVE_SNAPSHOT_BYTES = MAX_TARGET_EVENTS * 16_384
MAX_NATIVE_SNAPSHOT_NODES = MAX_TARGET_EVENTS * 256
MAX_REPLAY_MS = 10_000
RESPONSE_WAIT_SECONDS = 1.5
_SOURCE_HOST = "pcm.kakaocdn.net"
_SOURCE_PATH = re.compile(r"^/dna/[^/?#]+/[^/?#]+/[^/?#]+/i[^/?#]+\.jpg$")
# Only live-observed 1200px-high tile grids; unknown dimensions stay on fallback.
_OBSERVED_TILE_COLUMNS = {764: 16, 842: 17, 844: 17}
_ALLOWED_CONTEXT_ATTRIBUTES = frozenset(
    {"alpha", "colorSpace", "colorType", "desynchronized", "toneMapping", "willReadFrequently"}
)


class NativeCaptureUnavailable(Exception):
    """A native-source optimization proof was absent or unsupported."""

    def __init__(
        self, reason: str, *, bytes_read: int = 0, unsafe_live_change: bool = False
    ) -> None:
        super().__init__(reason)
        self.reason = reason
        self.bytes_read = bytes_read
        self.unsafe_live_change = unsafe_live_change


@dataclass(frozen=True, slots=True)
class NativeCapture:
    result: CaptureResult
    source_mime: str = "image/jpeg"
    backdrop: str = "verified_solid_white"
    encoding_fallback_reason: str | None = None
    source_bytes: int = 0
    source_url: str = ""
    target_signature: tuple[Any, ...] = ()
    source_signature: tuple[Any, ...] = ()
    paint_snapshot: dict[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class ValidatedTrace:
    source_url: str
    width: int
    height: int
    draws: tuple[dict[str, Any], ...]
    context_attributes: dict[str, Any]
    initial_dimensions: tuple[int, int]


TRACE_INIT_SCRIPT = r"""(() => {
  if (window.__piccomaNativeCapture) return;
  const CANDIDATE_HOST = 'pcm.kakaocdn.net';
  const MAX_TARGET_EVENTS = 512, MAX_RETAINED = 16,
    MAX_ACTIVE_TRACES = 128, MAX_TOTAL_EVENTS = 20000;
  const nativeJsonStringify = JSON.stringify;
  const canvasIds = new WeakMap(), imageIds = new WeakMap(), imageStates = new WeakMap();
  const traces = new WeakMap(), retained = new Map(), heavyTraces = new Map();
  const expectedAttributeMutations = new WeakMap();
  let nextId = 1, totalEvents = 0, totalOverflow = false;
  const ignoredCanvases = new WeakSet(), ignoredImages = new WeakSet();
  const hooks = { imageProperties: {}, dimensions: {}, attributes: {}, paint: {}, attributeValueHookReady: false };
  const native = {
    createElement: Document.prototype.createElement,
    getContext: HTMLCanvasElement.prototype.getContext,
    drawImage: CanvasRenderingContext2D.prototype.drawImage,
    setTransform: CanvasRenderingContext2D.prototype.setTransform,
    getTransform: CanvasRenderingContext2D.prototype.getTransform,
    width: Object.getOwnPropertyDescriptor(HTMLCanvasElement.prototype, 'width'),
    height: Object.getOwnPropertyDescriptor(HTMLCanvasElement.prototype, 'height'),
    setAttribute: Element.prototype.setAttribute,
    removeAttribute: Element.prototype.removeAttribute,
    setAttributeNS: Element.prototype.setAttributeNS,
    removeAttributeNS: Element.prototype.removeAttributeNS,
    setAttributeNode: Element.prototype.setAttributeNode,
    setAttributeNodeNS: Element.prototype.setAttributeNodeNS,
    removeAttributeNode: Element.prototype.removeAttributeNode,
    namedSet: NamedNodeMap.prototype.setNamedItem,
    namedSetNS: NamedNodeMap.prototype.setNamedItemNS,
    namedRemove: NamedNodeMap.prototype.removeNamedItem,
    namedRemoveNS: NamedNodeMap.prototype.removeNamedItemNS,
    attrValue: Object.getOwnPropertyDescriptor(Attr.prototype, 'value')
  };
  const objectId = (map, value) => {
    let id = map.get(value);
    if (!id) { id = `o${nextId++}`; map.set(value, id); }
    return id;
  };
  const newTrace = canvas => ({
    owner: canvas, id: objectId(canvasIds, canvas), initialDimensions: [canvas.width, canvas.height],
    events: [], sources: new Map(), sourceOverflow: false,
    attributeObserver: null,
    unobservedAttributeMutation: false,
    generation: 0, retired: totalOverflow,
    overflow: false, resetGeneration: 0, lastTouched: totalEvents
  });
  const monitorOnlyTrace = canvas => {
    let trace = traces.get(canvas);
    if (!trace) {
      trace = newTrace(canvas);
      trace.owner = null;
      trace.retired = true;
      traces.set(canvas, trace);
    }
    observeCanvasAttributes(canvas, trace);
    return trace;
  };
  const traceFor = canvas => {
    let trace = traces.get(canvas);
    if (!trace) { trace = newTrace(canvas); traces.set(canvas, trace); }
    return trace;
  };
  const retireTrace = (canvas, trace) => {
    if (trace.attributeObserver) trace.attributeObserver.disconnect();
    trace.attributeObserver = null;
    trace.events.length = 0;
    trace.sources.clear();
    trace.retired = true;
    trace.owner = null;
    retained.delete(canvas);
    heavyTraces.delete(canvas);
  };
  const retain = (canvas, trace) => {
    if (retained.has(canvas) || trace.retired || totalOverflow || trace.overflow) return;
    while (retained.size >= MAX_RETAINED) {
      const oldest = retained.keys().next().value;
      if (!oldest) break;
      const oldTrace = retained.get(oldest);
      if (oldTrace) retireTrace(oldest, oldTrace);
      else retained.delete(oldest);
    }
    retained.set(canvas, trace);
    observeCanvasAttributes(canvas, trace);
  };
  const retireAllHeavyTraces = () => {
    for (const [canvas, trace] of [...heavyTraces.entries()]) retireTrace(canvas, trace);
    retained.clear();
  };
  const append = (trace, event) => {
    trace.generation++;
    if (trace.retired) return;
    if (totalOverflow) return;
    const canvas = trace.owner;
    if (!heavyTraces.has(canvas)) {
      while (heavyTraces.size >= MAX_ACTIVE_TRACES) {
        const oldest = heavyTraces.keys().next().value;
        const oldTrace = oldest && heavyTraces.get(oldest);
        if (!oldest) break;
        if (oldTrace) retireTrace(oldest, oldTrace);
        else heavyTraces.delete(oldest);
      }
      heavyTraces.set(canvas, trace);
    }
    totalEvents++;
    if (totalEvents > MAX_TOTAL_EVENTS) {
      totalOverflow = true;
      retireAllHeavyTraces();
      if (!trace.retired) retireTrace(canvas, trace);
      return;
    }
    if (trace.events.length >= MAX_TARGET_EVENTS) {
      trace.overflow = true;
      retireTrace(canvas, trace);
      return;
    }
    trace.events.push({ ...event, resetGeneration: trace.resetGeneration });
    trace.lastTouched = totalEvents;
  };
  const recordAttributeDimensionMutation = (canvas, name, operation) => {
    if (!(canvas instanceof HTMLCanvasElement) || ignoredCanvases.has(canvas)) return;
    const dimension = String(name).toLowerCase();
    if (!['width', 'height'].includes(dimension)) return;
    const trace = traceFor(canvas), before = [canvas.width, canvas.height];
    trace.resetGeneration++;
    append(trace, { type: 'attribute_dimension_mutation', attribute: dimension,
      operation, before, after: [canvas.width, canvas.height] });
  };
  const expectAttributeMutation = (canvas, name, before, after) => {
    let expected = expectedAttributeMutations.get(canvas);
    if (!expected) { expected = []; expectedAttributeMutations.set(canvas, expected); }
    if (expected.length >= MAX_TARGET_EVENTS) {
      traceFor(canvas).unobservedAttributeMutation = true;
      return;
    }
    expected.push({ name, before, after });
    queueMicrotask(() => {
      if (expectedAttributeMutations.get(canvas) === expected)
        expectedAttributeMutations.delete(canvas);
    });
  };
  const observeCanvasAttributes = (canvas, trace) => {
    if (trace.attributeObserver || ignoredCanvases.has(canvas)) return;
    const observer = new MutationObserver(records => {
      for (let index = 0; index < records.length; index++) {
        const record = records[index], target = record.target;
        if (!(target instanceof HTMLCanvasElement) ||
            !['width', 'height'].includes(String(record.attributeName).toLowerCase())) continue;
        const name = String(record.attributeName).toLowerCase();
        let after = target.getAttribute(name);
        for (let next = index + 1; next < records.length; next++) {
          const candidate = records[next];
          if (candidate.target === target && candidate.attributeName === record.attributeName) {
            after = candidate.oldValue;
            break;
          }
        }
        const expected = expectedAttributeMutations.get(target) || [];
        const match = expected.findIndex(row => row.name === name &&
          row.before === record.oldValue && row.after === after);
        if (match >= 0) {
          expected.splice(match, 1);
          if (!expected.length) expectedAttributeMutations.delete(target);
        } else {
          trace.unobservedAttributeMutation = true;
          trace.resetGeneration++;
          append(trace, { type: 'unobserved_attribute_mutation', attribute: name });
        }
      }
    });
    observer.observe(canvas, { attributes: true, attributeOldValue: true,
      attributeFilter: ['width', 'height'] });
    trace.attributeObserver = observer;
  };
  const imageState = image => {
    let state = imageStates.get(image);
    if (!state) {
      state = { assignmentGeneration: 0, loadGeneration: 0,
        lastLoadedAssignmentGeneration: null, lastLoadedSource: null, watched: false };
      imageStates.set(image, state);
    }
    if (!state.watched) {
      state.watched = true;
      image.addEventListener('load', () => {
        if (ignoredImages.has(image)) return;
        state.loadGeneration++;
        state.lastLoadedAssignmentGeneration = state.assignmentGeneration;
        state.lastLoadedSource = image.currentSrc || image.src || '';
      }, true);
    }
    return state;
  };
  const noteImageAssignment = image => {
    if (!(image instanceof HTMLImageElement) || ignoredImages.has(image)) return;
    const state = imageState(image);
    state.assignmentGeneration++;
    state.lastLoadedAssignmentGeneration = null;
    state.lastLoadedSource = null;
  };
  const parseSource = source => {
    if (!(source instanceof HTMLImageElement)) return null;
    const raw = source.currentSrc || source.src || '';
    try {
      const parsed = new URL(raw, location.href);
      return parsed.protocol === 'https:' && parsed.hostname === CANDIDATE_HOST
        ? { raw, host: parsed.hostname, path: parsed.pathname }
        : null;
    } catch (_) { return null; }
  };
  const stateSnapshot = context => {
    const transform = native.getTransform.call(context);
    return {
      alpha: context.globalAlpha,
      composite: context.globalCompositeOperation,
      filter: context.filter,
      smoothing: context.imageSmoothingEnabled,
      smoothingQuality: context.imageSmoothingQuality,
      shadowBlur: context.shadowBlur,
      shadowColor: context.shadowColor,
      shadowOffsetX: context.shadowOffsetX,
      shadowOffsetY: context.shadowOffsetY,
      transform: [transform.a, transform.b, transform.c, transform.d, transform.e, transform.f],
      clipCount: 0
    };
  };
  const rememberCanvasCreation = canvas => { if (canvas instanceof HTMLCanvasElement) traceFor(canvas); };

  const createElementHook = function(name, options) {
    const value = native.createElement.call(this, name, options);
    if (String(name).toLowerCase() === 'canvas') rememberCanvasCreation(value);
    return value;
  };
  Document.prototype.createElement = createElementHook;
  for (const [name, descriptor] of [['width', native.width], ['height', native.height]]) {
    if (!descriptor || !descriptor.get || !descriptor.set) continue;
    const dimensionHook = function(value) {
      if (ignoredCanvases.has(this)) { descriptor.set.call(this, value); return; }
      const trace = traceFor(this);
      const before = [this.width, this.height];
      const beforeAttribute = this.getAttribute(name);
      descriptor.set.call(this, value);
      expectAttributeMutation(this, name, beforeAttribute, this.getAttribute(name));
      trace.resetGeneration++;
      append(trace, { type: 'dimension_set', dimension: name,
        requested: Number(value), before, after: [this.width, this.height] });
    };
    hooks.dimensions[name] = dimensionHook;
    Object.defineProperty(HTMLCanvasElement.prototype, name, {
      configurable: descriptor.configurable, enumerable: descriptor.enumerable,
      get: descriptor.get,
      set: dimensionHook
    });
  }
  const dimensionAttributeSetHook = function(name, value) {
    const isDimension = this instanceof HTMLCanvasElement && !ignoredCanvases.has(this) &&
      (String(name).toLowerCase() === 'width' || String(name).toLowerCase() === 'height');
    const trace = isDimension ? traceFor(this) : null;
    const before = trace ? [this.width, this.height] : null;
    const attributeBefore = trace ? this.getAttribute(String(name).toLowerCase()) : null;
    native.setAttribute.call(this, name, value);
    if (trace) {
      expectAttributeMutation(this, String(name).toLowerCase(), attributeBefore,
        this.getAttribute(String(name).toLowerCase()));
      trace.resetGeneration++;
      append(trace, { type: 'attribute_dimension_set', attribute: String(name).toLowerCase(),
        value: String(value), before, after: [this.width, this.height] });
    }
  };
  Element.prototype.setAttribute = dimensionAttributeSetHook;
  const dimensionAttributeRemoveHook = function(name) {
    const isDimension = this instanceof HTMLCanvasElement && !ignoredCanvases.has(this) &&
      (String(name).toLowerCase() === 'width' || String(name).toLowerCase() === 'height');
    const trace = isDimension ? traceFor(this) : null;
    const before = trace ? [this.width, this.height] : null;
    const attributeBefore = trace ? this.getAttribute(String(name).toLowerCase()) : null;
    native.removeAttribute.call(this, name);
    if (trace) {
      expectAttributeMutation(this, String(name).toLowerCase(), attributeBefore,
        this.getAttribute(String(name).toLowerCase()));
      trace.resetGeneration++;
      append(trace, { type: 'attribute_dimension_remove', attribute: String(name).toLowerCase(),
        before, after: [this.width, this.height] });
    }
  };
  Element.prototype.removeAttribute = dimensionAttributeRemoveHook;
  const setAttributeNSHook = function(namespace, qualifiedName, value) {
    const localName = String(qualifiedName).split(':').pop().toLowerCase();
    const result = native.setAttributeNS.call(this, namespace, qualifiedName, value);
    recordAttributeDimensionMutation(this, localName, 'setAttributeNS');
    return result;
  };
  hooks.attributes.setAttributeNS = setAttributeNSHook;
  Element.prototype.setAttributeNS = setAttributeNSHook;
  const removeAttributeNSHook = function(namespace, localName) {
    const result = native.removeAttributeNS.call(this, namespace, localName);
    recordAttributeDimensionMutation(this, localName, 'removeAttributeNS');
    return result;
  };
  hooks.attributes.removeAttributeNS = removeAttributeNSHook;
  Element.prototype.removeAttributeNS = removeAttributeNSHook;
  const setAttributeNodeHook = function(attribute) {
    const result = native.setAttributeNode.call(this, attribute);
    recordAttributeDimensionMutation(this, attribute?.localName || attribute?.name, 'setAttributeNode');
    return result;
  };
  hooks.attributes.setAttributeNode = setAttributeNodeHook;
  Element.prototype.setAttributeNode = setAttributeNodeHook;
  const setAttributeNodeNSHook = function(attribute) {
    const result = native.setAttributeNodeNS.call(this, attribute);
    recordAttributeDimensionMutation(this, attribute?.localName || attribute?.name, 'setAttributeNodeNS');
    return result;
  };
  hooks.attributes.setAttributeNodeNS = setAttributeNodeNSHook;
  Element.prototype.setAttributeNodeNS = setAttributeNodeNSHook;
  const removeAttributeNodeHook = function(attribute) {
    const result = native.removeAttributeNode.call(this, attribute);
    recordAttributeDimensionMutation(this, attribute?.localName || attribute?.name, 'removeAttributeNode');
    return result;
  };
  hooks.attributes.removeAttributeNode = removeAttributeNodeHook;
  Element.prototype.removeAttributeNode = removeAttributeNodeHook;
  const namedMapHooks = [
    ['setNamedItem', native.namedSet],
    ['setNamedItemNS', native.namedSetNS],
    ['removeNamedItem', native.namedRemove],
    ['removeNamedItemNS', native.namedRemoveNS]
  ];
  for (const [name, original] of namedMapHooks) {
    if (typeof original !== 'function') continue;
    const hook = function(...args) {
      const result = original.apply(this, args);
      const attributeOrName = name === 'removeNamedItemNS' ? args[1] : args[0];
      const attrName = typeof attributeOrName === 'string'
        ? attributeOrName : (attributeOrName?.localName || attributeOrName?.name);
      recordAttributeDimensionMutation(this.ownerElement, attrName, name);
      return result;
    };
    hooks.attributes[name] = hook;
    NamedNodeMap.prototype[name] = hook;
  }
  if (native.attrValue?.get && native.attrValue?.set) {
    const attrValueHook = function(value) {
      const owner = this.ownerElement, name = this.localName || this.name;
      native.attrValue.set.call(this, value);
      recordAttributeDimensionMutation(owner, name, 'Attr.value');
    };
    hooks.attributes.attrValue = attrValueHook;
    Object.defineProperty(Attr.prototype, 'value', { ...native.attrValue, set: attrValueHook });
    hooks.attributeValueHookReady = true;
  }
  const getContextHook = function(type, options) {
    const context = arguments.length > 1
      ? native.getContext.call(this, type, options)
      : native.getContext.call(this, type);
    if (!ignoredCanvases.has(this) && context instanceof CanvasRenderingContext2D) {
      const trace = traceFor(this);
      const attributes = context.getContextAttributes ? context.getContextAttributes() : null;
      append(trace, { type: 'getContext', contextType: String(type), argumentCount: arguments.length,
        options: arguments.length > 1 ? options : null, attributes,
        canvasDimensions: [this.width, this.height] });
    }
    return context;
  };
  HTMLCanvasElement.prototype.getContext = getContextHook;

  const imageDescriptors = [
    [HTMLImageElement.prototype, 'src'],
    [HTMLImageElement.prototype, 'srcset'],
    [HTMLImageElement.prototype, 'sizes']
  ];
  for (const [prototype, name] of imageDescriptors) {
    const descriptor = Object.getOwnPropertyDescriptor(prototype, name);
    if (!descriptor || !descriptor.get || !descriptor.set) continue;
    const imagePropertyHook = function(value) {
      if (!ignoredImages.has(this)) noteImageAssignment(this);
      descriptor.set.call(this, value);
    };
    hooks.imageProperties[name] = imagePropertyHook;
    Object.defineProperty(prototype, name, {
      configurable: descriptor.configurable, enumerable: descriptor.enumerable,
      get: descriptor.get,
      set: imagePropertyHook
    });
  }
  const originalSetAttribute = Element.prototype.setAttribute;
  const sourceSetAttribute = function(name, value) {
    if (this instanceof HTMLImageElement && ['src', 'srcset', 'sizes'].includes(String(name).toLowerCase()))
      noteImageAssignment(this);
    return originalSetAttribute.call(this, name, value);
  };
  Element.prototype.setAttribute = sourceSetAttribute;

  const drawImageHook = function(source, ...args) {
    if (!ignoredCanvases.has(this.canvas)) {
      const trace = traceFor(this.canvas);
      const sourceInfo = parseSource(source);
      const state = source instanceof HTMLImageElement && !ignoredImages.has(source)
        ? imageState(source) : null;
      const sourceId = source && typeof source === 'object' ? objectId(imageIds, source) : null;
      if (sourceInfo && source instanceof HTMLImageElement && !ignoredImages.has(source) &&
          !trace.retired && !totalOverflow) {
        if (trace.sources.size >= 8 && !trace.sources.has(sourceId)) trace.sourceOverflow = true;
        else trace.sources.set(sourceId, source);
      }
      append(trace, { type: 'drawImage', sourceId,
        sourceKind: source instanceof HTMLImageElement ? 'HTMLImageElement' :
          (source == null ? 'null' : Object.prototype.toString.call(source).slice(8, -1)),
        sourceUrl: sourceInfo ? sourceInfo.raw : null,
        sourceWidth: source instanceof HTMLImageElement ? source.naturalWidth : 0,
        sourceHeight: source instanceof HTMLImageElement ? source.naturalHeight : 0,
        sourceComplete: source instanceof HTMLImageElement ? source.complete : false,
        assignmentGeneration: state ? state.assignmentGeneration : null,
        loadGeneration: state ? state.loadGeneration : null,
        lastLoadedAssignmentGeneration: source instanceof HTMLImageElement
          ? state?.lastLoadedAssignmentGeneration ?? null : null,
        lastLoadedSource: source instanceof HTMLImageElement ? state?.lastLoadedSource ?? null : null,
        args: args.map(value => typeof value === 'number' ? value : null),
        overload: args.length + 1, state: stateSnapshot(this),
        targetDimensions: [this.canvas.width, this.canvas.height] });
      if (sourceInfo && !ignoredCanvases.has(this.canvas) && !trace.retired && !totalOverflow)
        retain(this.canvas, trace);
    }
    return native.drawImage.call(this, source, ...args);
  };
  CanvasRenderingContext2D.prototype.drawImage = drawImageHook;
  const unsupportedPaint = ['clearRect', 'fillRect', 'strokeRect', 'fill', 'stroke',
    'fillText', 'strokeText', 'putImageData', 'drawFocusIfNeeded', 'reset'];
  for (const name of unsupportedPaint) {
    const original = CanvasRenderingContext2D.prototype[name];
    if (typeof original !== 'function') continue;
    const paintHook = function(...args) {
      if (!ignoredCanvases.has(this.canvas)) append(traceFor(this.canvas), { type: 'unsupported_paint', operation: name });
      return original.apply(this, args);
    };
    hooks.paint[name] = paintHook;
    CanvasRenderingContext2D.prototype[name] = paintHook;
  }
  const originalClip = CanvasRenderingContext2D.prototype.clip;
  const clipHook = function(...args) {
    if (!ignoredCanvases.has(this.canvas)) append(traceFor(this.canvas), { type: 'clip' });
    return originalClip.apply(this, args);
  };
  hooks.paint.clip = clipHook;
  CanvasRenderingContext2D.prototype.clip = clipHook;

  const rgba = color => {
    const m = String(color).match(/^rgba?\(\s*([\d.]+)[, ]+([\d.]+)[, ]+([\d.]+)(?:\s*[,/]\s*([\d.]+))?\s*\)$/i);
    return m ? [Number(m[1]), Number(m[2]), Number(m[3]), m[4] === undefined ? 1 : Number(m[4])] : null;
  };
  const pseudo = (node, which) => {
    const style = getComputedStyle(node, which);
    return { content: style.content, backgroundColor: style.backgroundColor,
      backgroundImage: style.backgroundImage, opacity: style.opacity,
      filter: style.filter, mixBlendMode: style.mixBlendMode };
  };
  const paintSnapshot = canvas => {
    const rows = [], pathNodes = [], rectOf = node => {
      const r = node.getBoundingClientRect(); return [r.x, r.y, r.width, r.height];
    };
    const canvasRect = rectOf(canvas);
    for (let node = canvas, depth = 0; node && depth < 16; node = node.parentElement, depth++) {
      pathNodes.push(node);
      const s = getComputedStyle(node), bg = rgba(s.backgroundColor), before = pseudo(node, '::before'), after = pseudo(node, '::after');
      rows.push({ id: objectId(canvasIds, node), tag: node.tagName, rect: rectOf(node),
        backgroundColor: s.backgroundColor, backgroundImage: s.backgroundImage,
        opacity: s.opacity, filter: s.filter, backdropFilter: s.backdropFilter || 'none',
        mixBlendMode: s.mixBlendMode, maskImage: s.maskImage || 'none', clipPath: s.clipPath,
        backgroundClip: s.backgroundClip, clip: s.clip,
        borderRadius: s.borderRadius,
        borderWidths: [s.borderTopWidth, s.borderRightWidth, s.borderBottomWidth, s.borderLeftWidth],
        boxShadow: s.boxShadow, overflow: s.overflow,
        transform: s.transform, visibility: s.visibility, display: s.display,
        before, after, alpha: bg ? bg[3] : null });
      if (!bg || bg[3] === 0) continue;
      const overlappingDescendants = [];
      for (const sibling of node.querySelectorAll('*')) {
        if (pathNodes.includes(sibling)) continue;
        const style = getComputedStyle(sibling), rect = rectOf(sibling);
        const visible = style.display !== 'none' && style.display !== 'contents' &&
          style.visibility === 'visible' && Number(style.opacity) > 0 && rect[2] > 0 && rect[3] > 0;
        const overlaps = rect[0] < canvasRect[0] + canvasRect[2] &&
          rect[1] < canvasRect[1] + canvasRect[3] &&
          rect[0] + rect[2] > canvasRect[0] && rect[1] + rect[3] > canvasRect[1];
        const before = pseudo(sibling, '::before'), after = pseudo(sibling, '::after');
        const pseudoPaints = [before, after].some(item => {
          const color = rgba(item.backgroundColor);
          return (item.content !== 'none' && item.content !== 'normal') ||
            item.backgroundImage !== 'none' || Boolean(color && color[3] > 0);
        });
        if (style.visibility === 'visible' && Number(style.opacity) > 0 &&
            ((visible && overlaps) || pseudoPaints)) overlappingDescendants.push({
          id: objectId(canvasIds, sibling), tag: sibling.tagName,
          classes: String(sibling.className || ''), rect,
          before, after
        });
      }
      const walker = document.createTreeWalker(node, NodeFilter.SHOW_TEXT);
      while (walker.nextNode()) {
        const textNode = walker.currentNode;
        if (!textNode.textContent?.trim() || pathNodes.includes(textNode.parentElement)) continue;
        const range = document.createRange();
        range.selectNodeContents(textNode);
        const r = range.getBoundingClientRect();
        if (r.width > 0 && r.height > 0 && r.left < canvasRect[0] + canvasRect[2] &&
            r.top < canvasRect[1] + canvasRect[3] &&
            r.right > canvasRect[0] && r.bottom > canvasRect[1])
          overlappingDescendants.push({ kind: 'text', rect: [r.x, r.y, r.width, r.height] });
      }
      return { canvasId: objectId(canvasIds, canvas), canvasRect,
        ancestors: rows, firstOpaqueIndex: rows.length - 1,
        overlappingDescendants,
        firstOpaqueColor: bg, firstOpaqueCoversCanvas:
          rows[rows.length - 1].rect[0] <= canvasRect[0] + 0.01 &&
          rows[rows.length - 1].rect[1] <= canvasRect[1] + 0.01 &&
          rows[rows.length - 1].rect[0] + rows[rows.length - 1].rect[2] >= canvasRect[0] + canvasRect[2] - 0.01 &&
          rows[rows.length - 1].rect[1] + rows[rows.length - 1].rect[3] >= canvasRect[1] + canvasRect[3] - 0.01 };
    }
    return { canvasId: objectId(canvasIds, canvas), canvasRect, ancestors: rows,
      firstOpaqueIndex: -1, overlappingDescendants: [],
      firstOpaqueColor: null, firstOpaqueCoversCanvas: false };
  };
  const snapshot = canvas => {
    // Parser-created canvases may not pass through Document.createElement or
    // a hooked drawing method before capture. Start a lightweight generation
    // baseline now; it cannot prove prior drawing history, but it can make
    // any mutation during capture fail closed.
    const trace = monitorOnlyTrace(canvas);
    const sourceStates = [...trace.sources.entries()].map(([id, image]) => {
      const state = imageState(image);
      return { id, currentSrc: image.currentSrc || '', src: image.src || '',
        assignmentGeneration: state.assignmentGeneration,
        loadGeneration: state.loadGeneration,
        lastLoadedAssignmentGeneration: state.lastLoadedAssignmentGeneration,
        lastLoadedSource: state.lastLoadedSource,
        complete: image.complete, naturalWidth: image.naturalWidth,
        naturalHeight: image.naturalHeight };
    });
    return { id: trace.id, initialDimensions: trace.initialDimensions,
      dimensions: [canvas.width, canvas.height], connected: canvas.isConnected,
      generation: trace.generation, retired: trace.retired,
      overflow: trace.overflow, totalOverflow, events: trace.events.map(event => ({ ...event })),
      sourceStates, sourceOverflow: trace.sourceOverflow,
      unobservedAttributeMutation: trace.unobservedAttributeMutation,
      attributeObserverReady: trace.attributeObserver !== null,
      paint: paintSnapshot(canvas), retained: retained.has(canvas), hooksIntact:
        Document.prototype.createElement === createElementHook &&
        HTMLCanvasElement.prototype.getContext === getContextHook &&
        CanvasRenderingContext2D.prototype.drawImage === drawImageHook &&
        Element.prototype.setAttribute === sourceSetAttribute &&
        Element.prototype.removeAttribute === dimensionAttributeRemoveHook &&
        Object.getOwnPropertyDescriptor(HTMLCanvasElement.prototype, 'width')?.set === hooks.dimensions.width &&
        Object.getOwnPropertyDescriptor(HTMLCanvasElement.prototype, 'height')?.set === hooks.dimensions.height &&
        Object.getOwnPropertyDescriptor(HTMLImageElement.prototype, 'src')?.set === hooks.imageProperties.src &&
        Object.getOwnPropertyDescriptor(HTMLImageElement.prototype, 'srcset')?.set === hooks.imageProperties.srcset &&
        Object.getOwnPropertyDescriptor(HTMLImageElement.prototype, 'sizes')?.set === hooks.imageProperties.sizes &&
        hooks.attributeValueHookReady === true &&
        Object.entries(hooks.attributes).every(([name, hook]) => {
          if (name === 'setAttributeNS') return Element.prototype.setAttributeNS === hook;
          if (name === 'removeAttributeNS') return Element.prototype.removeAttributeNS === hook;
          if (name === 'setAttributeNode') return Element.prototype.setAttributeNode === hook;
          if (name === 'setAttributeNodeNS') return Element.prototype.setAttributeNodeNS === hook;
          if (name === 'removeAttributeNode') return Element.prototype.removeAttributeNode === hook;
          if (name === 'attrValue') return Object.getOwnPropertyDescriptor(Attr.prototype, 'value')?.set === hook;
          return NamedNodeMap.prototype[name] === hook;
        }) &&
        Object.entries(hooks.paint).every(([name, hook]) => CanvasRenderingContext2D.prototype[name] === hook) &&
        trace.attributeObserver !== null };
  };
  const snapshotJson = canvas => {
    const MAX_BYTES = __MAX_BYTES__, MAX_NODES = __MAX_NODES__;
    const fail = () => { throw new TypeError('native_snapshot_not_json_safe'); };
    if (JSON.stringify !== nativeJsonStringify ||
        Array.prototype.toJSON !== undefined || Object.prototype.toJSON !== undefined)
      fail();
    const value = window.__piccomaNativeCapture.snapshot(canvas);
    if (value === null) return 'null';
    const required = ['id', 'initialDimensions', 'dimensions', 'connected',
      'generation', 'retired', 'overflow', 'totalOverflow', 'events',
      'sourceStates', 'sourceOverflow', 'unobservedAttributeMutation',
      'attributeObserverReady', 'paint', 'retained', 'hooksIntact'];
    if (!value || typeof value !== 'object' || Array.isArray(value) ||
        Object.getPrototypeOf(value) !== Object.prototype ||
        required.some(key => !Object.prototype.hasOwnProperty.call(value, key))) fail();

    let nodes = 0, estimatedBytes = 0;
    const active = new WeakSet();
    const account = bytes => {
      estimatedBytes += bytes;
      if (estimatedBytes > MAX_BYTES) fail();
    };
    const stringBytes = text => {
      let bytes = 2;
      for (let index = 0; index < text.length; index++) {
        const code = text.charCodeAt(index);
        if (code === 34 || code === 92 || code === 8 || code === 9 ||
            code === 10 || code === 12 || code === 13) bytes += 2;
        else if (code < 32) bytes += 6;
        else if (code >= 0xd800 && code <= 0xdbff) {
          const next = text.charCodeAt(index + 1);
          if (next >= 0xdc00 && next <= 0xdfff) { bytes += 4; index++; }
          else bytes += 6;
        } else if (code >= 0xdc00 && code <= 0xdfff) bytes += 6;
        else if (code < 0x80) bytes++;
        else if (code < 0x800) bytes += 2;
        else bytes += 3;
        if (bytes > MAX_BYTES) fail();
      }
      return bytes;
    };
    const validate = item => {
      if (++nodes > MAX_NODES) fail();
      if (item === null) { account(4); return; }
      if (typeof item === 'string') { account(stringBytes(item)); return; }
      if (typeof item === 'boolean') { account(item ? 4 : 5); return; }
      if (typeof item === 'number') {
        if (!Number.isFinite(item) || Object.is(item, -0)) fail();
        const numberText = nativeJsonStringify(item);
        account(numberText.length);
        return;
      }
      if (typeof item !== 'object' || active.has(item)) fail();
      active.add(item);
      if (Array.isArray(item)) {
        if (Object.getPrototypeOf(item) !== Array.prototype ||
            Reflect.ownKeys(item).length !== item.length + 1) fail();
        account(2);
        for (let index = 0; index < item.length; index++) {
          if (index > 0) account(1);
          const descriptor = Object.getOwnPropertyDescriptor(item, String(index));
          if (!descriptor || !descriptor.enumerable || !Object.prototype.hasOwnProperty.call(descriptor, 'value')) fail();
          validate(descriptor.value);
        }
        active.delete(item);
        return;
      }
      if (Object.getPrototypeOf(item) !== Object.prototype) fail();
      const keys = Reflect.ownKeys(item);
      if (keys.length > MAX_NODES) fail();
      account(2);
      for (let index = 0; index < keys.length; index++) {
        if (index > 0) account(1);
        const key = keys[index];
        if (typeof key !== 'string') fail();
        const descriptor = Object.getOwnPropertyDescriptor(item, key);
        if (!descriptor || !descriptor.enumerable || !Object.prototype.hasOwnProperty.call(descriptor, 'value')) fail();
        account(stringBytes(key) + 1);
        validate(descriptor.value);
      }
      active.delete(item);
    };
    validate(value);
    const serialized = nativeJsonStringify(value);
    if (typeof serialized !== 'string' ||
        new TextEncoder().encode(serialized).byteLength !== estimatedBytes) fail();
    return serialized;
  };
  const retire = canvas => {
    const trace = traces.get(canvas);
    if (trace) retireTrace(canvas, trace);
    else retained.delete(canvas);
  };
  const replay = async (base64Bytes, specification) => {
    let objectUrl = null, replayCanvas = null;
    try {
      const binary = atob(base64Bytes), bytes = new Uint8Array(binary.length);
      for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
      objectUrl = URL.createObjectURL(new Blob([bytes], { type: 'image/jpeg' }));
      const image = new Image(); ignoredImages.add(image); image.src = objectUrl; await image.decode();
      if (image.naturalWidth !== specification.width || image.naturalHeight !== specification.height)
        throw new Error('decoded_source_dimensions');
      replayCanvas = document.createElement('canvas');
      ignoredCanvases.add(replayCanvas);
      if (replayCanvas.width !== specification.initialWidth || replayCanvas.height !== specification.initialHeight)
        throw new Error('initial_canvas_dimensions');
      const ctx = specification.contextArgumentCount === 1
        ? replayCanvas.getContext('2d')
        : replayCanvas.getContext('2d', specification.contextOptions);
      if (!ctx || !ctx.getContextAttributes) throw new Error('context_attributes_unavailable');
      replayCanvas.width = specification.width;
      replayCanvas.height = specification.height;
      const actualAttributes = ctx.getContextAttributes();
      if (JSON.stringify(actualAttributes) !== JSON.stringify(specification.contextAttributes))
        throw new Error('context_attributes_mismatch');
      for (const draw of specification.draws) {
        const state = draw.state;
        ctx.setTransform(...state.transform);
        ctx.globalAlpha = state.alpha;
        ctx.globalCompositeOperation = state.composite;
        ctx.filter = state.filter;
        ctx.imageSmoothingEnabled = state.smoothing;
        ctx.imageSmoothingQuality = state.smoothingQuality;
        ctx.shadowBlur = state.shadowBlur;
        ctx.shadowColor = state.shadowColor;
        ctx.shadowOffsetX = state.shadowOffsetX;
        ctx.shadowOffsetY = state.shadowOffsetY;
        native.drawImage.call(ctx, image, ...draw.args);
      }
      return { dataUrl: replayCanvas.toDataURL('image/png'),
        dimensions: [replayCanvas.width, replayCanvas.height],
        contextAttributes: actualAttributes, drawCount: specification.draws.length };
    } finally {
      if (replayCanvas) { replayCanvas.width = 1; replayCanvas.height = 1; }
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    }
  };
  window.__piccomaNativeCapture = { snapshot, paintSnapshot, retire, replay,
    snapshotJson,
    limits: { perTarget: MAX_TARGET_EVENTS, retained: MAX_RETAINED,
      activeTraces: MAX_ACTIVE_TRACES, total: MAX_TOTAL_EVENTS } };
})();"""
TRACE_INIT_SCRIPT = TRACE_INIT_SCRIPT.replace(
    "__MAX_BYTES__", str(MAX_NATIVE_SNAPSHOT_BYTES)
).replace("__MAX_NODES__", str(MAX_NATIVE_SNAPSHOT_NODES))


SNAPSHOT_JSON_EXPRESSION = r"""(node) => {
  const api = window.__piccomaNativeCapture;
  if (api === undefined || api === null) return 'null';
  if (typeof api.snapshotJson !== 'function')
    throw new TypeError('native_snapshot_json_unavailable');
  return api.snapshotJson(node);
}"""

_NATIVE_SNAPSHOT_FIELDS = frozenset({
    "id", "initialDimensions", "dimensions", "connected", "generation",
    "retired", "overflow", "totalOverflow", "events", "sourceStates",
    "sourceOverflow", "unobservedAttributeMutation", "attributeObserverReady",
    "paint", "retained", "hooksIntact",
})
_NATIVE_SNAPSHOT_BOOLEAN_FIELDS = (
    "connected", "retired", "overflow", "totalOverflow", "sourceOverflow",
    "unobservedAttributeMutation", "attributeObserverReady", "retained", "hooksIntact",
)


def _duplicate_free_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON object key")
        result[key] = value
    return result


def _parse_json_constant(value: str) -> None:
    raise ValueError(f"unsupported JSON constant: {value}")


def _parse_json_integer(value: str) -> int:
    if value == "-0":
        raise ValueError("negative zero is unsupported in native snapshots")
    return int(value)


def _parse_json_float(value: str) -> float:
    parsed = float(value)
    if not math.isfinite(parsed) or (parsed == 0 and math.copysign(1.0, parsed) < 0):
        raise ValueError("non-finite or negative-zero JSON number")
    return parsed


def _native_snapshot_shape_is_valid(value: object) -> bool:
    if not isinstance(value, dict) or not _NATIVE_SNAPSHOT_FIELDS.issubset(value):
        return False
    if not isinstance(value.get("id"), str) or not value["id"]:
        return False
    for key in ("initialDimensions", "dimensions"):
        dimensions = value.get(key)
        if (
            not isinstance(dimensions, list)
            or len(dimensions) != 2
            or any(type(dimension) is not int or dimension < 0 for dimension in dimensions)
        ):
            return False
    if type(value.get("generation")) is not int or value["generation"] < 0:
        return False
    if any(type(value.get(key)) is not bool for key in _NATIVE_SNAPSHOT_BOOLEAN_FIELDS):
        return False
    events = value.get("events")
    if (
        not isinstance(events, list)
        or len(events) > MAX_TARGET_EVENTS
        or any(not isinstance(event, dict) or not isinstance(event.get("type"), str) for event in events)
    ):
        return False
    source_states = value.get("sourceStates")
    if not isinstance(source_states, list) or len(source_states) > MAX_TARGET_EVENTS:
        return False
    if any(not isinstance(state, dict) for state in source_states):
        return False
    paint = value.get("paint")
    return isinstance(paint, dict)


def _decode_native_snapshot_json(value: object) -> dict[str, Any] | None:
    """Restore a bounded full trace, rejecting lossy or ambiguous JSON input."""

    if not isinstance(value, str) or len(value) > MAX_NATIVE_SNAPSHOT_BYTES:
        raise NativeCaptureUnavailable(
            "native_snapshot_json_invalid", unsafe_live_change=True
        )
    try:
        if len(value.encode("utf-8")) > MAX_NATIVE_SNAPSHOT_BYTES:
            raise ValueError("native snapshot JSON exceeds the transport bound")
        decoded = json.loads(
            value,
            object_pairs_hook=_duplicate_free_object,
            parse_constant=_parse_json_constant,
            parse_int=_parse_json_integer,
            parse_float=_parse_json_float,
        )
    except (UnicodeEncodeError, ValueError, TypeError, RecursionError) as exc:
        raise NativeCaptureUnavailable(
            "native_snapshot_json_invalid", unsafe_live_change=True
        ) from exc
    if decoded is None:
        return None
    if not _native_snapshot_shape_is_valid(decoded):
        raise NativeCaptureUnavailable(
            "native_snapshot_schema_invalid", unsafe_live_change=True
        )
    return decoded


async def _read_native_snapshot(page: Page, canvas: Any) -> dict[str, Any] | None:
    """Fetch one full trace as JSON and restore it for the existing validators."""

    try:
        raw = await _bounded_evaluate(
            canvas, SNAPSHOT_JSON_EXPRESSION, timeout_seconds=3.0
        )
    except Exception as exc:
        raise NativeCaptureUnavailable(
            "native_snapshot_transport_failed", unsafe_live_change=True
        ) from exc
    return _decode_native_snapshot_json(raw)


def validate_tile_trace(
    trace: dict[str, Any] | None, *, expected_width: int, expected_height: int
) -> ValidatedTrace:
    """Accept only a complete live-observed 384/408-image draw graph."""

    if (
        not isinstance(trace, dict)
        or trace.get("hooksIntact") is not True
        or trace.get("overflow")
        or trace.get("totalOverflow")
        or trace.get("sourceOverflow")
        or trace.get("unobservedAttributeMutation")
    ):
        raise NativeCaptureUnavailable("trace_missing_or_overflow")
    if (
        trace.get("connected") is not True
        or trace.get("dimensions") != [expected_width, expected_height]
        or expected_width not in _OBSERVED_TILE_COLUMNS
        or expected_height != 1200
        or trace.get("retained") is not True
    ):
        raise NativeCaptureUnavailable("target_canvas_identity_or_dimensions")
    events = trace.get("events")
    if not isinstance(events, list) or not 1 <= len(events) <= MAX_TARGET_EVENTS:
        raise NativeCaptureUnavailable("target_trace_incomplete")
    columns = _OBSERVED_TILE_COLUMNS[expected_width]
    expected_draw_count = columns * 24
    if len(events) != expected_draw_count + 3:
        raise NativeCaptureUnavailable("unsupported_target_operation_count")
    creation = events[0]
    if (
        not isinstance(creation, dict)
        or creation.get("type") != "getContext"
        or creation.get("contextType") != "2d"
        or creation.get("argumentCount") != 1
        or creation.get("options") is not None
        or creation.get("canvasDimensions") != [300, 150]
    ):
        raise NativeCaptureUnavailable("unsupported_context_creation")
    attributes = creation.get("attributes")
    if (
        not isinstance(attributes, dict)
        or not _ALLOWED_CONTEXT_ATTRIBUTES.issuperset(attributes)
        or attributes.get("alpha") is not True
        or attributes.get("colorSpace") != "srgb"
    ):
        raise NativeCaptureUnavailable("unsupported_context_attributes")
    resets = events[1:3]
    expected_resets = [
        ("width", expected_width, [300, 150], [expected_width, 150]),
        ("height", expected_height, [expected_width, 150], [expected_width, expected_height]),
    ]
    for event, (dimension, value, before, after) in zip(resets, expected_resets, strict=True):
        if (
            not isinstance(event, dict)
            or event.get("type") != "dimension_set"
            or event.get("dimension") != dimension
            or event.get("requested") != value
            or event.get("before") != before
            or event.get("after") != after
        ):
            raise NativeCaptureUnavailable("unsupported_canvas_reset_sequence")

    draws: list[dict[str, Any]] = []
    source_url: str | None = None
    source_id: str | None = None
    source_generation: tuple[int, int, int] | None = None
    source_grid: set[tuple[int, int, int, float]] = set()
    destination_grid: set[tuple[int, int, int, int]] = set()
    expected_sources: set[tuple[int, int, int, float]] = set()
    expected_destinations: set[tuple[int, int, int, int]] = set()
    for row in range(24):
        sy = row * 50
        for column in range(columns):
            sx = column * 50
            expected_sources.add((sx, sy, min(50, expected_width - sx), 50.01))
            dx, dy = sx, sy
            expected_destinations.add(
                (dx, dy, min(50, expected_width - dx), 50)
            )

    expected_state = {
        "alpha": 1,
        "composite": "source-over",
        "filter": "none",
        "smoothing": True,
        "smoothingQuality": "low",
        "shadowBlur": 0,
        "shadowColor": "rgba(0, 0, 0, 0)",
        "shadowOffsetX": 0,
        "shadowOffsetY": 0,
        "transform": [1, 0, 0, 1, 0, 0],
        "clipCount": 0,
    }
    for event in events[3:]:
        if not isinstance(event, dict) or event.get("type") != "drawImage":
            raise NativeCaptureUnavailable("unsupported_canvas_paint_or_operation")
        args = event.get("args")
        if (
            event.get("overload") != 9
            or not isinstance(args, list)
            or len(args) != 8
            or any(type(value) not in {int, float} or not math.isfinite(value) for value in args)
            or event.get("state") != expected_state
            or event.get("targetDimensions") != [expected_width, expected_height]
            or event.get("sourceKind") != "HTMLImageElement"
            or event.get("sourceComplete") is not True
            or event.get("sourceWidth") != expected_width
            or event.get("sourceHeight") != expected_height
        ):
            raise NativeCaptureUnavailable("unsupported_draw_source_state_or_geometry")
        raw_url = event.get("sourceUrl")
        if not isinstance(raw_url, str):
            raise NativeCaptureUnavailable("source_url_missing")
        parsed = urlparse(raw_url)
        if (
            parsed.scheme != "https"
            or parsed.hostname != _SOURCE_HOST
            or parsed.port not in {None, 443}
            or parsed.username is not None
            or parsed.password is not None
            or parsed.fragment
            or _SOURCE_PATH.fullmatch(parsed.path) is None
            or not parsed.query
        ):
            raise NativeCaptureUnavailable("source_url_unrecognized")
        if source_url is None:
            source_url = raw_url
            source_id = event.get("sourceId")
        if raw_url != source_url or event.get("sourceId") != source_id:
            raise NativeCaptureUnavailable("mixed_source_objects_or_urls")
        generations = (
            event.get("assignmentGeneration"),
            event.get("loadGeneration"),
            event.get("lastLoadedAssignmentGeneration"),
        )
        if (
            any(type(value) is not int or value < 1 for value in generations)
            or generations[0] != generations[2]
            or event.get("lastLoadedSource") != raw_url
        ):
            raise NativeCaptureUnavailable("source_load_generation_unstable")
        if source_generation is None:
            source_generation = generations
        elif generations != source_generation:
            raise NativeCaptureUnavailable("source_reloaded_during_canvas_generation")
        sx, sy, sw, sh, dx, dy, dw, dh = args
        source_rect = (sx, sy, sw, sh)
        destination_rect = (dx, dy, dw, dh)
        if (
            any(type(value) is not int for value in (sx, sy, dx, dy, dw, dh))
            or type(sw) not in {int, float}
            or type(sh) not in {int, float}
        ):
            raise NativeCaptureUnavailable("non_numeric_or_fractional_origin")
        source_grid.add(source_rect)
        destination_grid.add(destination_rect)
        draws.append({"args": args, "state": event["state"]})
    if (
        len(draws) != expected_draw_count
        or len(source_grid) != expected_draw_count
        or source_grid != expected_sources
        or len(destination_grid) != expected_draw_count
        or destination_grid != expected_destinations
        or source_url is None
        or source_id is None
    ):
        raise NativeCaptureUnavailable("source_or_destination_tile_grid_incomplete")
    source_states = trace.get("sourceStates")
    if not isinstance(source_states, list) or len(source_states) != 1:
        raise NativeCaptureUnavailable("source_object_state_unavailable")
    source_state = source_states[0]
    if (
        not isinstance(source_state, dict)
        or source_state.get("id") != source_id
        or source_state.get("currentSrc") != source_url
        or source_state.get("src") != source_url
        or source_state.get("assignmentGeneration") != source_generation[0]
        or source_state.get("loadGeneration") != source_generation[1]
        or source_state.get("lastLoadedAssignmentGeneration") != source_generation[2]
        or source_state.get("lastLoadedSource") != source_url
        or source_state.get("complete") is not True
        or source_state.get("naturalWidth") != expected_width
        or source_state.get("naturalHeight") != expected_height
    ):
        raise NativeCaptureUnavailable("source_object_state_unstable")
    return ValidatedTrace(
        source_url=source_url,
        width=expected_width,
        height=expected_height,
        draws=tuple(draws),
        context_attributes=attributes,
        initial_dimensions=(300, 150),
    )


def validate_white_paint_path(
    snapshot: dict[str, Any] | None, *, width: int, height: int
) -> bool:
    """Prove the observed transparent-canvas to covering-white paint path."""

    if not isinstance(snapshot, dict) or snapshot.get("firstOpaqueCoversCanvas") is not True:
        return False
    rect = snapshot.get("canvasRect")
    rows = snapshot.get("ancestors")
    overlapping_descendants = snapshot.get("overlappingDescendants")
    first_opaque = snapshot.get("firstOpaqueIndex")
    color = snapshot.get("firstOpaqueColor")
    if (
        snapshot.get("canvasId") is None
        or not isinstance(rect, list)
        or len(rect) != 4
        or abs(rect[2] - width) > 0.5
        or abs(rect[3] - height) > 0.5
        or not isinstance(rows, list)
        or not isinstance(first_opaque, int)
        or first_opaque < 1
        or first_opaque >= len(rows)
        or not isinstance(color, list)
        or color != [255, 255, 255, 1]
        or not isinstance(overlapping_descendants, list)
        or overlapping_descendants
    ):
        return False
    for index, row in enumerate(rows[: first_opaque + 1]):
        if not isinstance(row, dict):
            return False
        transparent = index < first_opaque
        alpha = row.get("alpha")
        if (
            row.get("display") in {"none", "contents"}
            or row.get("visibility") != "visible"
            or row.get("opacity") != "1"
            or row.get("backgroundImage") != "none"
            or row.get("filter") != "none"
            or row.get("backdropFilter") != "none"
            or row.get("mixBlendMode") != "normal"
            or row.get("maskImage") != "none"
            or row.get("clipPath") != "none"
            or row.get("clip") != "auto"
            or row.get("backgroundClip") != "border-box"
            or row.get("borderWidths") != ["0px", "0px", "0px", "0px"]
            or row.get("borderRadius") != "0px"
            or row.get("boxShadow") != "none"
            or row.get("before", {}).get("content") != "none"
            or row.get("after", {}).get("content") != "none"
            or row.get("before", {}).get("backgroundImage") != "none"
            or row.get("after", {}).get("backgroundImage") != "none"
            or row.get("before", {}).get("backgroundColor") != "rgba(0, 0, 0, 0)"
            or row.get("after", {}).get("backgroundColor") != "rgba(0, 0, 0, 0)"
            or row.get("before", {}).get("filter") != "none"
            or row.get("after", {}).get("filter") != "none"
            or row.get("before", {}).get("opacity") != "1"
            or row.get("after", {}).get("opacity") != "1"
            or row.get("before", {}).get("mixBlendMode") != "normal"
            or row.get("after", {}).get("mixBlendMode") != "normal"
            or not _identity_transform(row.get("transform"))
            or (transparent and alpha != 0)
            or (not transparent and (alpha != 1 or row.get("backgroundColor") != "rgb(255, 255, 255)"))
        ):
            return False
        node_rect = row.get("rect")
        if not isinstance(node_rect, list) or len(node_rect) != 4:
            return False
        if (
            node_rect[0] > rect[0] + 0.01
            or node_rect[1] > rect[1] + 0.01
            or node_rect[0] + node_rect[2] < rect[0] + rect[2] - 0.01
            or node_rect[1] + node_rect[3] < rect[1] + rect[3] - 0.01
        ):
            return False
    return True


def _identity_transform(value: object) -> bool:
    if value == "none":
        return True
    if not isinstance(value, str):
        return False
    match = re.fullmatch(
        r"matrix\(\s*([-+\d.eE]+),\s*([-+\d.eE]+),\s*([-+\d.eE]+),\s*([-+\d.eE]+),\s*([-+\d.eE]+),\s*([-+\d.eE]+)\s*\)",
        value,
    )
    if match is None:
        return False
    try:
        return tuple(float(item) for item in match.groups()) == (1, 0, 0, 1, 0, 0)
    except ValueError:
        return False


def composite_replay_png_on_white(data: bytes, *, width: int, height: int) -> bytes:
    """Composite verified transparent source-native pixels onto proven white."""

    try:
        with Image.open(io.BytesIO(data)) as image:
            if image.format != "PNG" or image.size != (width, height):
                raise NativeCaptureUnavailable("replay_png_dimensions_or_format")
            rgba = image.convert("RGBA")
            background = Image.new("RGBA", (width, height), (255, 255, 255, 255))
            background.alpha_composite(rgba)
            output = io.BytesIO()
            background.convert("RGB").save(output, format="PNG")
            return output.getvalue()
    except NativeCaptureUnavailable:
        raise
    except Exception as exc:
        raise NativeCaptureUnavailable("replay_png_invalid") from exc


def encode_lossless_webp(data: bytes, *, width: int, height: int) -> CaptureResult:
    """Encode already-composited RGB pixels as lossless WebP and verify every RGB byte."""

    try:
        with Image.open(io.BytesIO(data)) as image:
            if image.format != "PNG" or image.size != (width, height):
                raise NativeCaptureUnavailable("webp_input_png_invalid")
            rgb = image.convert("RGB")
        if not features.check("webp"):
            raise NativeCaptureUnavailable("webp_codec_unavailable")
        encoded = io.BytesIO()
        rgb.save(encoded, format="WEBP", lossless=True, method=6)
        webp_bytes = encoded.getvalue()
        if not _has_single_lossless_vp8l_chunk(
            webp_bytes, width=width, height=height
        ):
            raise NativeCaptureUnavailable("webp_output_not_single_vp8l")
        with Image.open(io.BytesIO(webp_bytes)) as decoded:
            if decoded.format != "WEBP" or decoded.size != (width, height):
                raise NativeCaptureUnavailable("webp_output_format_or_dimensions_invalid")
            if decoded.convert("RGB").tobytes() != rgb.tobytes():
                raise NativeCaptureUnavailable("webp_rgb_round_trip_mismatch")
        return CaptureResult(
            data=webp_bytes,
            width=width,
            height=height,
            mime_type="image/webp",
            file_extension=".webp",
        )
    except NativeCaptureUnavailable:
        raise
    except Exception as exc:
        raise NativeCaptureUnavailable("webp_encode_failed") from exc


def encode_lossless_webp_or_png(
    data: bytes, *, width: int, height: int
) -> tuple[CaptureResult, str | None]:
    """Prefer verified lossless WebP; retain verified PNG pixels if encoding fails."""

    png_result = CaptureResult(data, width, height, "image/png", ".png")
    if not capture_result_format_is_valid(png_result, width=width, height=height):
        raise NativeCaptureUnavailable("webp_fallback_png_invalid")
    with Image.open(io.BytesIO(data)) as image:
        image.convert("RGB").load()
    try:
        return encode_lossless_webp(data, width=width, height=height), None
    except NativeCaptureUnavailable as exc:
        return (
            CaptureResult(
                data=data,
                width=width,
                height=height,
                mime_type="image/png",
                file_extension=".png",
            ),
            exc.reason,
        )


def capture_result_format_is_valid(result: CaptureResult, *, width: int, height: int) -> bool:
    """Validate result format, extension, and decoded dimensions for supported outputs."""

    if (result.width, result.height) != (width, height):
        return False
    expected = {
        ("image/png", ".png"): "PNG",
        ("image/webp", ".webp"): "WEBP",
    }.get((result.mime_type, result.file_extension))
    if expected is None:
        return False
    if expected == "PNG" and not result.data.startswith(b"\x89PNG\r\n\x1a\n"):
        return False
    if expected == "WEBP" and not _has_single_lossless_vp8l_chunk(
        result.data, width=width, height=height
    ):
        return False
    try:
        with Image.open(io.BytesIO(result.data)) as verification:
            if (
                verification.format != expected
                or verification.size != (width, height)
                or getattr(verification, "n_frames", 1) != 1
                or getattr(verification, "is_animated", False)
            ):
                return False
            verification.verify()
        with Image.open(io.BytesIO(result.data)) as image:
            if (
                image.format != expected
                or image.size != (width, height)
                or getattr(image, "n_frames", 1) != 1
                or getattr(image, "is_animated", False)
            ):
                return False
            image.load()
            return True
    except Exception:  # noqa: BLE001 - malformed image bytes are a validation failure
        return False


def _has_single_lossless_vp8l_chunk(
    data: bytes, *, width: int, height: int
) -> bool:
    """Require the exact simple lossless WebP container emitted for RGB output."""

    if (
        len(data) < 25
        or data[:4] != b"RIFF"
        or int.from_bytes(data[4:8], "little") != len(data) - 8
        or data[8:12] != b"WEBP"
        or data[12:16] != b"VP8L"
    ):
        return False
    chunk_size = int.from_bytes(data[16:20], "little")
    payload_start = 20
    payload_end = payload_start + chunk_size
    padded_end = payload_end + (chunk_size & 1)
    if chunk_size < 5 or padded_end != len(data) or data[payload_start] != 0x2F:
        return False
    width_minus_one = data[21] | ((data[22] & 0x3F) << 8)
    height_minus_one = (
        (data[22] >> 6)
        | (data[23] << 2)
        | ((data[24] & 0x0F) << 10)
    )
    has_alpha = (data[24] >> 4) & 1
    version = (data[24] >> 5) & 0x07
    return (
        width_minus_one + 1 == width
        and height_minus_one + 1 == height
        and has_alpha == 0
        and version == 0
    )


def validate_source_jpeg(data: bytes, *, width: int, height: int) -> None:
    """Require the observed one-frame baseline 4:4:4 JPEG layout."""

    if len(data) < 4 or len(data) > MAX_SOURCE_BYTES or not data.startswith(b"\xff\xd8"):
        raise NativeCaptureUnavailable("source_body_not_bounded_jpeg")
    offset = 2
    frame: tuple[int, int, int, tuple[int, ...]] | None = None
    scans = 0
    try:
        while offset < len(data):
            if data[offset] != 0xFF:
                raise NativeCaptureUnavailable("source_jpeg_marker_invalid")
            while offset < len(data) and data[offset] == 0xFF:
                offset += 1
            if offset >= len(data):
                break
            marker = data[offset]
            offset += 1
            if marker == 0xD9:
                break
            if marker in {0x01, *range(0xD0, 0xD8)}:
                continue
            if offset + 2 > len(data):
                raise NativeCaptureUnavailable("source_jpeg_segment_truncated")
            length = int.from_bytes(data[offset : offset + 2], "big")
            if length < 2 or offset + length > len(data):
                raise NativeCaptureUnavailable("source_jpeg_segment_invalid")
            payload_start = offset + 2
            payload_end = offset + length
            if marker in {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}:
                if marker != 0xC0 or payload_end - payload_start < 6:
                    raise NativeCaptureUnavailable("source_jpeg_not_observed_baseline")
                precision = data[payload_start]
                frame_height = int.from_bytes(data[payload_start + 1 : payload_start + 3], "big")
                frame_width = int.from_bytes(data[payload_start + 3 : payload_start + 5], "big")
                components = data[payload_start + 5]
                expected_end = payload_start + 6 + components * 3
                if expected_end != payload_end or components != 3:
                    raise NativeCaptureUnavailable("source_jpeg_components_unsupported")
                sampling = tuple(data[payload_start + 7 + index * 3] for index in range(components))
                frame = (precision, frame_width, frame_height, sampling)
            elif marker == 0xDA:
                scans += 1
            offset = payload_end
            if marker == 0xDA:
                # Entropy data has byte stuffing; scan to the next non-restart marker.
                while offset < len(data) - 1:
                    if data[offset] == 0xFF and data[offset + 1] != 0x00:
                        break
                    offset += 2 if data[offset] == 0xFF and data[offset + 1] == 0x00 else 1
    except NativeCaptureUnavailable:
        raise
    except Exception as exc:
        raise NativeCaptureUnavailable("source_jpeg_parse_failed") from exc
    if (
        frame is None
        or frame != (8, width, height, (0x11, 0x11, 0x11))
        or scans != 1
    ):
        raise NativeCaptureUnavailable("source_jpeg_layout_unrecognized")
    try:
        with Image.open(io.BytesIO(data)) as image:
            if image.format != "JPEG" or image.size != (width, height) or getattr(image, "n_frames", 1) != 1:
                raise NativeCaptureUnavailable("source_jpeg_decode_mismatch")
            image.verify()
    except NativeCaptureUnavailable:
        raise
    except Exception as exc:
        raise NativeCaptureUnavailable("source_jpeg_decode_failed") from exc


def _decode_replay_data_url(value: object) -> bytes:
    if not isinstance(value, str) or not value.startswith("data:image/png;base64,"):
        raise NativeCaptureUnavailable("replay_png_unavailable")
    try:
        return base64.b64decode(value.split(",", 1)[1], validate=True)
    except Exception as exc:
        raise NativeCaptureUnavailable("replay_png_decode_failed") from exc


async def _bounded_evaluate(
    subject: Any,
    expression: str,
    argument: object = None,
    *,
    timeout_seconds: float,
) -> Any:
    """Bound Playwright evaluation without relying on a nonexistent timeout kwarg."""

    operation = (
        subject.evaluate(expression)
        if argument is None
        else subject.evaluate(expression, argument)
    )
    return await asyncio.wait_for(operation, timeout=timeout_seconds)


def _target_signature(snapshot: dict[str, Any]) -> tuple[Any, ...]:
    events = snapshot.get("events")
    if not isinstance(events, list):
        return ()
    draws = [event for event in events if isinstance(event, dict) and event.get("type") == "drawImage"]
    return (
        snapshot.get("id"), snapshot.get("connected"), snapshot.get("generation"),
        snapshot.get("retired"), snapshot.get("retained"),
        snapshot.get("hooksIntact"), snapshot.get("dimensions"), snapshot.get("initialDimensions"),
        len(events), snapshot.get("overflow"), snapshot.get("totalOverflow"),
        snapshot.get("sourceOverflow"), snapshot.get("unobservedAttributeMutation"),
        tuple(
            tuple((key, value) for key, value in row.items() if key not in {
                "sourceId", "sourceUrl", "sourceWidth", "sourceHeight", "sourceComplete",
                "assignmentGeneration", "loadGeneration", "lastLoadedAssignmentGeneration",
                "lastLoadedSource", "sourceKind",
            })
            for row in draws
        ),
    )


def target_generation_signature(snapshot: dict[str, Any] | None) -> tuple[Any, ...] | None:
    """Return a source-independent signature for fail-closed target checks."""

    if (
        not isinstance(snapshot, dict)
        or snapshot.get("hooksIntact") is not True
        or snapshot.get("connected") is not True
        or snapshot.get("unobservedAttributeMutation")
        or not isinstance(snapshot.get("events"), list)
    ):
        return None
    return _target_signature(snapshot)


def _source_signature(snapshot: dict[str, Any]) -> tuple[Any, ...]:
    source_states = snapshot.get("sourceStates")
    if not isinstance(source_states, list):
        return ()
    return tuple(
        tuple(row.get(key) for key in (
            "id", "currentSrc", "src", "assignmentGeneration", "loadGeneration",
            "lastLoadedAssignmentGeneration", "lastLoadedSource", "complete",
            "naturalWidth", "naturalHeight",
        ))
        for row in source_states if isinstance(row, dict)
    )


async def capture_native_tile_replay(
    page: Page,
    *,
    canvas: Any,
    expected_width: int,
    expected_height: int,
    responses_for_url: Callable[[str], Awaitable[list[Response]]],
    response_count_for_url: Callable[[str], int],
    response_registry_overflowed: bool,
    bytes_already_read: int,
    max_episode_bytes: int,
) -> NativeCapture:
    """Materialize an exact selected source graph or report a safe fallback reason."""

    if response_registry_overflowed:
        raise NativeCaptureUnavailable("response_registry_overflow")
    try:
        before = await _read_native_snapshot(page, canvas)
        trace = validate_tile_trace(
            before, expected_width=expected_width, expected_height=expected_height
        )
        paint_before = before.get("paint") if isinstance(before, dict) else None
        if (
            not isinstance(paint_before, dict)
            or paint_before.get("canvasId") != before.get("id")
            or not validate_white_paint_path(
            paint_before, width=expected_width, height=expected_height
            )
        ):
            raise NativeCaptureUnavailable("white_backdrop_unproven")
        candidates = await responses_for_url(trace.source_url)
        if len(candidates) != 1 or response_count_for_url(trace.source_url) != 1:
            raise NativeCaptureUnavailable(
                "source_response_missing" if not candidates else "source_response_ambiguous"
            )
        response = candidates[0]
        request = response.request
        try:
            request_url = request.url
            redirected = request.redirected_from is not None
            resource_type = request.resource_type
        except Exception as exc:
            raise NativeCaptureUnavailable("source_response_request_unavailable") from exc
        if (
            response.url != trace.source_url
            or request_url != trace.source_url
            or redirected
            or resource_type != "image"
            or response.status != 200
            or response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
            != "image/jpeg"
        ):
            raise NativeCaptureUnavailable("source_response_not_exact_terminal_jpeg")
        content_length = response.headers.get("content-length")
        try:
            declared_length = int(content_length) if content_length is not None else 0
        except ValueError as exc:
            raise NativeCaptureUnavailable("source_body_length_invalid") from exc
        if declared_length <= 0:
            raise NativeCaptureUnavailable("source_body_length_missing")
        if declared_length > MAX_SOURCE_BYTES:
            raise NativeCaptureUnavailable("source_body_over_limit")
        remaining_budget = max_episode_bytes - bytes_already_read
        if remaining_budget <= 0 or declared_length > remaining_budget:
            raise NativeCaptureUnavailable("episode_source_byte_budget_exhausted")
        try:
            body = await asyncio.wait_for(response.body(), timeout=5.0)
        except Exception as exc:
            raise NativeCaptureUnavailable("source_body_unavailable") from exc
        if (
            len(body) != declared_length
            or len(body) > MAX_SOURCE_BYTES
            or bytes_already_read + len(body) > max_episode_bytes
        ):
            raise NativeCaptureUnavailable("source_body_length_mismatch", bytes_read=len(body))
        validate_source_jpeg(body, width=expected_width, height=expected_height)
        specification = {
            "width": trace.width,
            "height": trace.height,
            "initialWidth": trace.initial_dimensions[0],
            "initialHeight": trace.initial_dimensions[1],
            "contextArgumentCount": 1,
            "contextOptions": None,
            "contextAttributes": trace.context_attributes,
            "draws": list(trace.draws),
        }
        encoded = base64.b64encode(body).decode("ascii")
        replayed = await _bounded_evaluate(
            page,
            "async ([bytes, spec]) => window.__piccomaNativeCapture.replay(bytes, spec)",
            [encoded, specification],
            timeout_seconds=MAX_REPLAY_MS / 1000,
        )
        if (
            not isinstance(replayed, dict)
            or replayed.get("dimensions") != [expected_width, expected_height]
            or replayed.get("contextAttributes") != trace.context_attributes
            or replayed.get("drawCount") != len(trace.draws)
        ):
            raise NativeCaptureUnavailable("replay_output_unverified")
        after = await _read_native_snapshot(page, canvas)
        if (
            not isinstance(after, dict)
            or _target_signature(before) != _target_signature(after)
        ):
            raise NativeCaptureUnavailable(
                "live_target_changed_during_replay", bytes_read=len(body), unsafe_live_change=True
            )
        if _source_signature(before) != _source_signature(after):
            raise NativeCaptureUnavailable(
                "source_generation_changed_during_replay", bytes_read=len(body)
            )
        if (
            before.get("paint") != after.get("paint")
            or after.get("paint", {}).get("canvasId") != after.get("id")
            or not validate_white_paint_path(
                after.get("paint"), width=expected_width, height=expected_height
            )
        ):
            raise NativeCaptureUnavailable(
                "paint_path_changed_during_replay", bytes_read=len(body), unsafe_live_change=True
            )
        replay_png = _decode_replay_data_url(replayed.get("dataUrl"))
        composited = composite_replay_png_on_white(
            replay_png, width=expected_width, height=expected_height
        )
        output_result, encoding_fallback_reason = encode_lossless_webp_or_png(
            composited, width=expected_width, height=expected_height
        )
        final_snapshot = await _read_native_snapshot(page, canvas)
        if (
            not isinstance(final_snapshot, dict)
            or _target_signature(before) != _target_signature(final_snapshot)
        ):
            raise NativeCaptureUnavailable(
                "live_target_changed_after_composite", bytes_read=len(body), unsafe_live_change=True
            )
        if _source_signature(before) != _source_signature(final_snapshot):
            raise NativeCaptureUnavailable(
                "source_generation_changed_after_composite", bytes_read=len(body)
            )
        if (
            before.get("paint") != final_snapshot.get("paint")
            or final_snapshot.get("paint", {}).get("canvasId") != final_snapshot.get("id")
            or not validate_white_paint_path(
                final_snapshot.get("paint"), width=expected_width, height=expected_height
            )
        ):
            raise NativeCaptureUnavailable(
                "paint_path_changed_after_composite", bytes_read=len(body), unsafe_live_change=True
            )
        if response_count_for_url(trace.source_url) != 1:
            raise NativeCaptureUnavailable("source_response_became_ambiguous", bytes_read=len(body))
        return NativeCapture(
            result=output_result,
            source_bytes=len(body),
            encoding_fallback_reason=encoding_fallback_reason,
            source_url=trace.source_url,
            target_signature=_target_signature(before),
            source_signature=_source_signature(before),
            paint_snapshot=before.get("paint"),
        )
    except NativeCaptureUnavailable as exc:
        if "body" in locals() and exc.bytes_read == 0:
            exc.bytes_read = len(body)
        raise
    except Exception as exc:
        bytes_read = len(body) if "body" in locals() else 0
        raise NativeCaptureUnavailable("native_replay_failed", bytes_read=bytes_read) from exc


async def validate_native_capture_still_current(
    page: Page, canvas: Any, capture: NativeCapture
) -> str | None:
    """Check target/source generations after adapter-level capture guards."""

    try:
        current = await _read_native_snapshot(page, canvas)
    except Exception as exc:
        raise NativeCaptureUnavailable(
            "live_target_recheck_failed", unsafe_live_change=True
        ) from exc
    if (
        not isinstance(current, dict)
        or _target_signature(current) != capture.target_signature
        or current.get("paint") != capture.paint_snapshot
        or current.get("paint", {}).get("canvasId") != current.get("id")
        or current.get("hooksIntact") is not True
    ):
        raise NativeCaptureUnavailable(
            "live_target_changed_after_adapter_checks", unsafe_live_change=True
        )
    if _source_signature(current) != capture.source_signature:
        return "source_generation_changed_after_adapter_checks"
    return None


async def install_native_trace(page: Page) -> None:
    """Install bounded metadata-only hooks before any viewer resources load."""

    await page.add_init_script(TRACE_INIT_SCRIPT)


async def snapshot_native_trace(page: Page, canvas: Any) -> dict[str, Any] | None:
    """Read the current canvas trace without exposing it in logs or manifests."""

    return await _read_native_snapshot(page, canvas)


async def retire_native_trace(page: Page, canvas: Any) -> None:
    """Release the selected canvas/source object references after its capture."""

    try:
        await _bounded_evaluate(
            canvas,
            "node => window.__piccomaNativeCapture?.retire(node)",
            timeout_seconds=1.0,
        )
    except Exception:  # noqa: BLE001 - the page may have navigated or closed
        return


__all__ = [
    "MAX_NATIVE_SNAPSHOT_BYTES",
    "MAX_NATIVE_SNAPSHOT_NODES",
    "MAX_RETAINED_CANVASES",
    "MAX_SOURCE_BYTES",
    "MAX_TARGET_EVENTS",
    "SNAPSHOT_JSON_EXPRESSION",
    "TRACE_INIT_SCRIPT",
    "NativeCapture",
    "NativeCaptureUnavailable",
    "capture_native_tile_replay",
    "capture_result_format_is_valid",
    "composite_replay_png_on_white",
    "encode_lossless_webp",
    "encode_lossless_webp_or_png",
    "install_native_trace",
    "retire_native_trace",
    "snapshot_native_trace",
    "target_generation_signature",
    "validate_native_capture_still_current",
    "validate_source_jpeg",
    "validate_tile_trace",
    "validate_white_paint_path",
]
