"""Site-local source-canvas snapshots for the Hanayume reader."""

from __future__ import annotations

import base64
import binascii
import io
from dataclasses import dataclass

from PIL import Image, UnidentifiedImageError, features

from screenshot_crawler.core.capture import CaptureResult
from screenshot_crawler.core.errors import UnknownPageStateError

MAX_CANDIDATES = 8
MAX_IMAGE_BYTES = 8_000_000
# Episode sizes vary; these bounds limit memory rather than select one page size.
MAX_NATIVE_SIDE = 4_096
MAX_NATIVE_PIXELS = 4_000_000
MAX_CACHED_SOURCE_PIXELS = 12_000_000


def valid_native_dimensions(width: object, height: object) -> bool:
    return (
        type(width) is int and type(height) is int
        and 0 < width <= MAX_NATIVE_SIDE and 0 < height <= MAX_NATIVE_SIDE
        and width * height <= MAX_NATIVE_PIXELS
    )


OBSERVER_INIT_SCRIPT = r"""(() => {
  if (window.__hanayumeNativeCapture) return;
  const candidates = new Map();
  const lastSources = new WeakMap();
  const validDimensions = (width, height) => Number.isSafeInteger(width) &&
    Number.isSafeInteger(height) && width > 0 && height > 0 &&
    width <= __MAX_NATIVE_SIDE__ && height <= __MAX_NATIVE_SIDE__ &&
    width * height <= __MAX_NATIVE_PIXELS__;
  const states = new WeakMap();
  const attributeOwners = new WeakMap();
  const wrappers = [];
  let disabledReason = null;
  let nextProof = 1;
  const proofs = new Map();
  const stabilityNodeIds = new WeakMap();
  let nextStabilityNodeId = 1;
  const stabilityNodeId = node => {
    if (!node) return null;
    if (!stabilityNodeIds.has(node)) stabilityNodeIds.set(node, nextStabilityNodeId++);
    return stabilityNodeIds.get(node);
  };
  const nativeDraw = CanvasRenderingContext2D.prototype.drawImage;
  const nativeGetContext = HTMLCanvasElement.prototype.getContext;
  const nativeGetImageData = CanvasRenderingContext2D.prototype.getImageData;
  const nativeToDataURL = HTMLCanvasElement.prototype.toDataURL;
  const contextPrototype = CanvasRenderingContext2D.prototype;
  const nativeGetContextAttributes = contextPrototype.getContextAttributes;
  const nativeGetTransform = contextPrototype.getTransform;
  const nativeSetTransform = contextPrototype.setTransform;
  const trackedContextMethods = ['fillRect', 'strokeRect', 'clearRect', 'fill', 'stroke', 'fillText',
    'strokeText', 'putImageData', 'drawFocusIfNeeded', 'clip', 'drawImage', 'reset'];
  const contextStateProperties = ['globalAlpha', 'globalCompositeOperation', 'filter', 'imageSmoothingEnabled',
    'imageSmoothingQuality', 'shadowBlur', 'shadowOffsetX', 'shadowOffsetY', 'shadowColor'];
  const proofApiProperties = ['getContextAttributes', 'getTransform', 'setTransform', ...contextStateProperties];
  const proofApiDescriptors = new Map(proofApiProperties.map(name =>
    [name, Object.getOwnPropertyDescriptor(contextPrototype, name)]));
  wrappers.push(() => HTMLCanvasElement.prototype.getContext === nativeGetContext &&
    CanvasRenderingContext2D.prototype.getImageData === nativeGetImageData &&
    HTMLCanvasElement.prototype.toDataURL === nativeToDataURL);

  const stateFor = canvas => {
    let state = states.get(canvas);
    if (!state) {
      state = {generation: 0, writes: 0, clipUnsafe: false};
      states.set(canvas, state);
      canvas.addEventListener('contextlost', () => resetBitmap(canvas));
      canvas.addEventListener('contextrestored', () => resetBitmap(canvas));
    }
    return state;
  };
  const discard = canvas => candidates.delete(canvas);
  const bumpWrite = canvas => {
    const state = stateFor(canvas);
    state.writes += 1;
    discard(canvas);
    return state;
  };
  const resetBitmap = canvas => {
    const state = stateFor(canvas);
    state.generation += 1;
    state.writes += 1;
    state.clipUnsafe = false;
    discard(canvas);
  };
  const contextAttributes = context => {
    try {
      const value = typeof nativeGetContextAttributes === 'function'
        ? Reflect.apply(nativeGetContextAttributes, context, []) : null;
      if (!value) return null;
      return {
        alpha: value.alpha ?? null,
        colorSpace: value.colorSpace ?? null,
        colorType: value.colorType ?? null,
        desynchronized: value.desynchronized ?? null,
      };
    } catch (_) { return null; }
  };
  const identityTransform = context => {
    try {
      if (typeof nativeGetTransform !== 'function') return false;
      const value = Reflect.apply(nativeGetTransform, context, []);
      return value.a === 1 && value.b === 0 && value.c === 0 &&
        value.d === 1 && value.e === 0 && value.f === 0;
    } catch (_) { return false; }
  };
  const neutralShadow = context =>
    context.shadowBlur === 0 && context.shadowOffsetX === 0 &&
    context.shadowOffsetY === 0 &&
    String(context.shadowColor).replace(/\s+/g, '') === 'rgba(0,0,0,0)';
  const paintState = context => ({
    attributes: contextAttributes(context),
    identity: identityTransform(context),
    alpha: context.globalAlpha,
    composite: context.globalCompositeOperation,
    filter: context.filter || 'none',
    smoothing: context.imageSmoothingEnabled,
    smoothingQuality: context.imageSmoothingQuality,
    shadowBlur: context.shadowBlur,
    shadowOffsetX: context.shadowOffsetX,
    shadowOffsetY: context.shadowOffsetY,
    shadowColor: context.shadowColor,
    neutralShadow: neutralShadow(context),
  });
  const exactFullFrame = (args, source, target) =>
    args.length === 8 && args.every(Number.isSafeInteger) &&
    args[0] === 0 && args[1] === 0 && args[2] === source.width &&
    args[3] === source.height && args[4] === 0 && args[5] === 0 &&
    args[6] === target.width && args[7] === target.height &&
    validDimensions(source.width, source.height) && validDimensions(target.width, target.height);
  const locationOf = target => {
    const root = document.querySelector('#xCVPages');
    const wrapper = target.closest('.-cv-page');
    const holder = target.parentElement;
    if (!root || !wrapper || wrapper.parentElement !== root ||
        !holder?.classList.contains('-cv-page-canvas') ||
        holder.querySelectorAll('canvas').length !== 1) return null;
    const slot = [...root.children].indexOf(wrapper);
    const total = Number(document.querySelector('.-cv-f-page-total')?.textContent?.trim());
    if (!Number.isInteger(total) || total < 8 || slot < 1 || slot > total - 5) return null;
    const excluded = new Set(['mode-ci', 'mode-empty', 'mode-pr', 'mode-top-pr', 'mode-good', 'mode-last']);
    const classes = [...wrapper.classList];
    if (!classes.includes('-cv-page') || classes.some(name => excluded.has(name))) return null;
    if (classes.some(name => !['-cv-page', 'mode-loaded', 'mode-rendered', 'mode-req-render'].includes(name))) return null;
    return {root, wrapper, holder, slot, total};
  };
  const copyOptions = attributes => {
    const result = {};
    for (const key of ['alpha', 'colorSpace', 'colorType', 'desynchronized']) {
      const value = attributes?.[key];
      if (value !== null && value !== undefined) result[key] = value;
    }
    return result;
  };
  const eligible = (targetContext, source, args, location) => {
    if (!(source instanceof HTMLCanvasElement) || !location || !exactFullFrame(args, source, targetContext.canvas))
      return null;
    if (['width', 'height', 'getContext', 'toDataURL'].some(name => Object.hasOwn(source, name)))
      return null;
    const target = targetContext.canvas;
    const targetState = stateFor(target);
    const sourceContext = Reflect.apply(nativeGetContext, source, ['2d']);
    if (!sourceContext || targetState.clipUnsafe || Object.hasOwn(sourceContext, 'getContextAttributes') ||
        Object.hasOwn(sourceContext, 'getTransform') || Object.hasOwn(sourceContext, 'setTransform')) return null;
    const sourceAttrs = contextAttributes(sourceContext);
    const targetPaint = paintState(targetContext);
    if (!sourceAttrs || !targetPaint.attributes ||
        sourceAttrs.colorSpace !== 'srgb' || sourceAttrs.colorType !== 'unorm8' ||
        targetPaint.attributes.colorSpace !== 'srgb' || targetPaint.attributes.colorType !== 'unorm8' ||
        !targetPaint.identity || targetPaint.alpha !== 1 || targetPaint.composite !== 'source-over' ||
        targetPaint.filter !== 'none' || !targetPaint.neutralShadow) return null;
    return {target, source, sourceAttrs, targetPaint, targetState, location, episodePath: window.location.pathname};
  };
  const makeSnapshot = (source, sourceAttrs) => {
    const snapshot = document.createElement('canvas');
    snapshot.width = source.width;
    snapshot.height = source.height;
    const context = Reflect.apply(nativeGetContext, snapshot, ['2d', copyOptions(sourceAttrs)]);
    if (!context) return null;
    Reflect.apply(nativeDraw, context, [source, 0, 0]);
    return {canvas: snapshot, attributes: contextAttributes(context)};
  };
  const installMethod = (prototype, name, handler) => {
    const original = prototype?.[name];
    if (typeof original !== 'function') return;
    const wrapped = handler(original);
    try {
      Object.defineProperty(prototype, name, {configurable: true, writable: true, value: wrapped});
      wrappers.push(() => prototype[name] === wrapped);
    } catch (_) { disabledReason = 'hook_install_failed'; }
  };
  const installResetMethod = (prototype, name) => installMethod(prototype, name, original => function(...args) {
    const result = Reflect.apply(original, this, args);
    if (this?.canvas instanceof HTMLCanvasElement) resetBitmap(this.canvas);
    return result;
  });
  const writeMethods = ['fillRect', 'strokeRect', 'clearRect', 'fill', 'stroke', 'fillText', 'strokeText', 'putImageData', 'drawFocusIfNeeded'];
  for (const name of writeMethods) {
    if (name === 'drawImage') continue;
    installMethod(CanvasRenderingContext2D.prototype, name, original => function(...args) {
      const target = this?.canvas;
      if (target instanceof HTMLCanvasElement) bumpWrite(target);
      return Reflect.apply(original, this, args);
    });
  }
  installMethod(CanvasRenderingContext2D.prototype, 'clip', original => function(...args) {
    const result = Reflect.apply(original, this, args);
    if (this?.canvas instanceof HTMLCanvasElement) stateFor(this.canvas).clipUnsafe = true;
    return result;
  });
  if (typeof CanvasRenderingContext2D.prototype.reset === 'function')
    installResetMethod(CanvasRenderingContext2D.prototype, 'reset');
  installMethod(CanvasRenderingContext2D.prototype, 'drawImage', original => function(source, ...args) {
    const target = this?.canvas;
    if (!(target instanceof HTMLCanvasElement)) return Reflect.apply(original, this, [source, ...args]);
    let state = null;
    let prepared = null;
    try {
      state = bumpWrite(target);
      const location = locationOf(target);
      if (location && source instanceof HTMLCanvasElement) {
        lastSources.set(target, {width: source.width, height: source.height,
          supported: validDimensions(source.width, source.height)});
      }
      prepared = eligible(this, source, args, location);
      const cachedPixels = [...candidates.values()].reduce(
        (sum, candidate) => sum + candidate.sourceWidth * candidate.sourceHeight, 0);
      if (prepared && (candidates.size >= __MAX_CANDIDATES__ ||
          cachedPixels + source.width * source.height > __MAX_CACHED_SOURCE_PIXELS__)) {
        disabledReason = 'candidate_cache_overflow';
        candidates.clear();
      }
      if (prepared && !disabledReason) {
        const snapshot = makeSnapshot(source, prepared.sourceAttrs);
        if (!snapshot || !snapshot.attributes || snapshot.attributes.colorSpace !== 'srgb' ||
            snapshot.attributes.colorType !== 'unorm8') prepared = null;
        else prepared.snapshot = snapshot;
      } else prepared = null;
    } catch (_) {
      disabledReason = disabledReason || 'observer_integrity_lost';
      prepared = null;
      try {
        if (state) { state.writes += 1; discard(target); }
      } catch (_) { /* Preserve the page's original drawing behavior. */ }
    }
    let result;
    try {
      result = Reflect.apply(original, this, [source, ...args]);
    } catch (error) {
      try { discard(target); } catch (_) { /* Preserve the original exception. */ }
      throw error;
    }
    try {
      if (state) state.writes += 1;
      if (prepared && state && !disabledReason) {
        candidates.set(target, {
          target, wrapper: prepared.location.wrapper, episodePath: prepared.episodePath,
          slot: prepared.location.slot, total: prepared.location.total,
          generation: state.generation, writes: state.writes,
          targetWidth: target.width, targetHeight: target.height,
          sourceWidth: source.width, sourceHeight: source.height,
          sourceAttributes: prepared.sourceAttrs,
          snapshotAttributes: prepared.snapshot.attributes,
          targetPaint: prepared.targetPaint, snapshot: prepared.snapshot.canvas,
        });
      } else discard(target);
    } catch (_) {
      disabledReason = disabledReason || 'observer_integrity_lost';
      try { discard(target); } catch (_) { /* Preserve the original drawing result. */ }
    }
    return result;
  });

  for (const name of ['width', 'height']) {
    const descriptor = Object.getOwnPropertyDescriptor(HTMLCanvasElement.prototype, name);
    if (!descriptor?.get || !descriptor?.set) { disabledReason = 'canvas_size_hook_unavailable'; continue; }
    const getter = descriptor.get;
    const setter = descriptor.set;
    const wrappedGetter = function() { return Reflect.apply(getter, this, []); };
    const wrappedSetter = function(value) {
      Reflect.apply(setter, this, [value]);
      resetBitmap(this);
    };
    try {
      Object.defineProperty(HTMLCanvasElement.prototype, name, {
        configurable: descriptor.configurable, enumerable: descriptor.enumerable,
        get: wrappedGetter, set: wrappedSetter,
      });
      wrappers.push(() => {
        const current = Object.getOwnPropertyDescriptor(HTMLCanvasElement.prototype, name);
        return current?.get === wrappedGetter && current?.set === wrappedSetter;
      });
    } catch (_) { disabledReason = 'canvas_size_hook_failed'; }
  }
  const attributeMethods = ['setAttribute', 'setAttributeNS', 'removeAttribute', 'removeAttributeNS', 'setAttributeNode', 'setAttributeNodeNS', 'removeAttributeNode'];
  for (const name of attributeMethods) {
    installMethod(Element.prototype, name, original => function(...args) {
      let attributeName = '';
      if (name.includes('AttributeNode')) attributeName = args[0]?.name || '';
      else if (name.endsWith('NS')) attributeName = args[1] || '';
      else attributeName = args[0] || '';
      const isCanvasSize = this instanceof HTMLCanvasElement &&
        ['width', 'height'].includes(String(attributeName).toLowerCase());
      const result = Reflect.apply(original, this, args);
      if (isCanvasSize) resetBitmap(this);
      return result;
    });
  }
  const attributesDescriptor = Object.getOwnPropertyDescriptor(Element.prototype, 'attributes');
  if (attributesDescriptor?.get) {
    const getAttributes = attributesDescriptor.get;
    const wrappedGet = function() {
      const value = Reflect.apply(getAttributes, this, []);
      if (this instanceof HTMLCanvasElement && value) attributeOwners.set(value, this);
      return value;
    };
    try {
      Object.defineProperty(Element.prototype, 'attributes', {
        configurable: attributesDescriptor.configurable,
        enumerable: attributesDescriptor.enumerable,
        get: wrappedGet,
      });
      wrappers.push(() => Object.getOwnPropertyDescriptor(Element.prototype, 'attributes')?.get === wrappedGet);
    } catch (_) { disabledReason = 'canvas_attribute_owner_hook_failed'; }
  }
  for (const name of ['setNamedItem', 'setNamedItemNS', 'removeNamedItem', 'removeNamedItemNS']) {
    installMethod(NamedNodeMap.prototype, name, original => function(...args) {
      const canvas = attributeOwners.get(this);
      const attrName = name.startsWith('set')
        ? String(args[0]?.name || args[0]?.nodeName || '').toLowerCase()
        : String(args[name.endsWith('NS') ? 1 : 0] || '').toLowerCase();
      const result = Reflect.apply(original, this, args);
      if (canvas instanceof HTMLCanvasElement && ['width', 'height'].includes(attrName)) resetBitmap(canvas);
      return result;
    });
  }
  const attrValue = Object.getOwnPropertyDescriptor(Attr.prototype, 'value');
  if (attrValue?.get && attrValue?.set) {
    const getValue = attrValue.get;
    const setValue = attrValue.set;
    const wrappedGet = function() { return Reflect.apply(getValue, this, []); };
    const wrappedSet = function(value) {
      const owner = this.ownerElement;
      const reset = owner instanceof HTMLCanvasElement &&
        ['width', 'height'].includes(String(this.name).toLowerCase());
      Reflect.apply(setValue, this, [value]);
      if (reset) resetBitmap(owner);
    };
    try {
      Object.defineProperty(Attr.prototype, 'value', {
        configurable: attrValue.configurable, enumerable: attrValue.enumerable,
        get: wrappedGet, set: wrappedSet,
      });
      wrappers.push(() => {
        const current = Object.getOwnPropertyDescriptor(Attr.prototype, 'value');
        return current?.get === wrappedGet && current?.set === wrappedSet;
      });
    } catch (_) { disabledReason = 'canvas_attribute_hook_failed'; }
  }
  installMethod(HTMLCanvasElement.prototype, 'transferControlToOffscreen', original => function(...args) {
    discard(this);
    disabledReason = 'canvas_transferred_offscreen';
    return Reflect.apply(original, this, args);
  });

  const compare = (left, right) => {
    if (left.length !== right.length) return false;
    for (let index = 0; index < left.length; index += 1) if (left[index] !== right[index]) return false;
    return true;
  };
  const contextFor = canvas => Reflect.apply(nativeGetContext, canvas, ['2d']);
  const pngDataUrl = canvas => Reflect.apply(nativeToDataURL, canvas, ['image/png']);
  const pixels = canvas => {
    const context = contextFor(canvas);
    if (!context) throw new Error('canvas_readback_unavailable');
    return Reflect.apply(nativeGetImageData, context, [0, 0, canvas.width, canvas.height]).data;
  };
  const attrsEqual = (left, right) => left && right &&
    left.colorSpace === right.colorSpace && left.colorType === right.colorType && left.alpha === right.alpha;
  const paintStillSupported = paint => paint && paint.attributes?.colorSpace === 'srgb' &&
    paint.attributes?.colorType === 'unorm8' && paint.identity && paint.alpha === 1 &&
    paint.composite === 'source-over' && paint.filter === 'none' && paint.neutralShadow;
  const configureReplay = (context, candidate) => {
    if (typeof nativeSetTransform !== 'function') throw new Error('native_set_transform_unavailable');
    Reflect.apply(nativeSetTransform, context, [1, 0, 0, 1, 0, 0]);
    context.globalAlpha = 1;
    context.globalCompositeOperation = 'source-over';
    context.imageSmoothingEnabled = candidate.targetPaint.smoothing;
    context.imageSmoothingQuality = candidate.targetPaint.smoothingQuality;
    context.filter = 'none';
    context.shadowBlur = 0;
    context.shadowOffsetX = 0;
    context.shadowOffsetY = 0;
    context.shadowColor = 'rgba(0, 0, 0, 0)';
  };
  const currentObservation = () => {
    const viewer = document.querySelector('#comici-viewer');
    const pages = document.querySelector('#xCVPages');
    const seek = document.querySelector('#xCVSeekBar');
    const slots = pages ? [...pages.children].map((wrapper, index) => {
      const classes = [...wrapper.classList].sort();
      const wrapperRect = wrapper.getBoundingClientRect();
      const canvases = [...wrapper.querySelectorAll('canvas')];
      const canvas = canvases.length === 1 ? canvases[0] : null;
      const rect = canvas?.getBoundingClientRect();
      const visible = !!rect && rect.width > 0 && rect.height > 0 &&
        rect.left >= -1 && rect.top >= -1 && rect.right <= innerWidth + 1 && rect.bottom <= innerHeight + 1;
      const ready = !!canvas && classes.includes('mode-loaded') && classes.includes('mode-rendered') &&
        canvas.parentElement?.classList.contains('-cv-page-canvas') === true &&
        canvas.width > 0 && canvas.height > 0;
      return {
        index, classes,
        wrapper: [wrapperRect.x, wrapperRect.y, wrapperRect.width, wrapperRect.height],
        wrapperCenterInViewport: wrapperRect.width > 0 && wrapperRect.height > 0 &&
          wrapperRect.x + wrapperRect.width / 2 >= 0 && wrapperRect.x + wrapperRect.width / 2 <= innerWidth &&
          wrapperRect.y + wrapperRect.height / 2 >= 0 && wrapperRect.y + wrapperRect.height / 2 <= innerHeight,
        canvasCount: canvases.length,
        canvas: canvas ? {
          width: canvas.width, height: canvas.height,
          rect: [rect.x, rect.y, rect.width, rect.height],
          parentClasses: [...canvas.parentElement.classList].sort(), ready, visible,
        } : null,
      };
    }) : [];
    return {
      url: location.href,
      viewerCount: document.querySelectorAll('#comici-viewer').length,
      viewerClasses: viewer ? [...viewer.classList].sort() : [],
      pagesCount: document.querySelectorAll('#xCVPages').length,
      seekCount: document.querySelectorAll('#xCVSeekBar').length,
      currentText: document.querySelector('.-cv-f-page-current')?.textContent?.trim() ?? null,
      totalText: document.querySelector('.-cv-f-page-total')?.textContent?.trim() ?? null,
      seek: seek ? {type: seek.type, min: seek.min, max: seek.max, step: seek.step, value: seek.value} : null,
      viewport: {width: innerWidth, height: innerHeight}, slots,
    };
  };
  const integrityOk = () => wrappers.every(check => {
    try { return check(); } catch (_) { return false; }
  }) && [...proofApiDescriptors].every(([name, expected]) => {
    const actual = Object.getOwnPropertyDescriptor(contextPrototype, name);
    return actual?.value === expected?.value && actual?.get === expected?.get &&
      actual?.set === expected?.set && actual?.writable === expected?.writable &&
      actual?.enumerable === expected?.enumerable && actual?.configurable === expected?.configurable;
  });
  const bodyLayout = observation => {
    const total = Number(observation.totalText);
    const slots = observation.slots;
    const topEmpty = observation.viewerClasses.includes('mode-has-top-emptypage');
    // Match Python's observed shorter odd-total layout; exact blank/tail checks follow.
    if (!Number.isInteger(total) || total < 8 ||
        !(slots.length === total + 1 ||
          (total % 2 === 1 && slots.length === total))) return null;
    const last = slots.length - 1;
    const exactClasses = (index, expected) => {
      const row = slots[index];
      return row?.index === index && row.classes.length === expected.length &&
        expected.every(name => row.classes.includes(name));
    };
    const tails = [
      [0, ['-cv-page', 'mode-empty', 'mode-pr', 'mode-top-pr']],
      [last - 4, ['-cv-page', 'mode-ci']],
      [last - 3, ['-cv-page', 'mode-empty', 'mode-pr']],
      [last - 2, ['-cv-page', 'mode-empty', 'mode-pr']],
      [last - 1, ['-cv-page', 'mode-good']],
      [last, ['-cv-page', 'mode-last']],
    ];
    if (tails.some(([index, classes]) => !exactClasses(index, classes)) ||
        (topEmpty && (!exactClasses(1, ['-cv-page', 'mode-empty']) ||
          slots[1].canvasCount !== 0 || slots[1].canvas !== null))) return null;
    const start = topEmpty ? 2 : 1;
    const length = last - 4 - start;
    return length > 0 ? Array.from({length}, (_, offset) => start + offset) : null;
  };
  const api = {
    stability(expectedSlots) {
      // Read counters/identity only; preserve draw-time source candidates for capture.
      if (!integrityOk()) return null;
      const pages = document.querySelector('#xCVPages');
      return expectedSlots.map(slot => {
        const wrapper = pages?.children[slot];
        const canvases = wrapper?.querySelectorAll('canvas');
        const canvas = canvases?.length === 1 ? canvases[0] : null;
        const state = canvas ? stateFor(canvas) : null;
        return {slot, wrapperId: stabilityNodeId(wrapper), canvasId: stabilityNodeId(canvas),
          generation: state?.generation ?? null, writes: state?.writes ?? null};
      });
    },
    collect({expectedSlots, expectedCurrent, expectedBodyTotal, expectedBodySlots,
             hasTopEmptyPage, episodePath}) {
      proofs.clear();
      const observation = currentObservation();
      const current = Number(observation.currentText);
      const total = Number(observation.totalText);
      const observedTopEmpty = observation.viewerClasses.includes('mode-has-top-emptypage');
      const expectedLayoutSlots = bodyLayout(observation);
      const expectedLayoutValid = expectedLayoutSlots !== null && Array.isArray(expectedBodySlots) &&
        expectedBodySlots.length === expectedLayoutSlots.length &&
        expectedBodySlots.every((slot, index) => slot === expectedLayoutSlots[index]) &&
        observedTopEmpty === hasTopEmptyPage;
      if (location.pathname !== episodePath || location.search || location.hash || !Array.isArray(expectedSlots) ||
          current !== expectedCurrent || !Array.isArray(expectedBodySlots) ||
          expectedBodySlots.length !== expectedBodyTotal ||
          !expectedLayoutValid ||
          expectedSlots.some(slot => !expectedBodySlots.includes(slot))) return {ok: false, reason: 'selected_page_changed', observation};
      const selected = [];
      for (const index of expectedSlots) {
        const row = observation.slots[index];
        const wrapper = document.querySelector('#xCVPages')?.children[index];
        const canvas = wrapper?.querySelector('canvas');
        if (!row || row.index !== index || row.canvasCount !== 1 || !row.canvas?.ready || !row.canvas.visible ||
            !row.classes.includes('mode-loaded') || !row.classes.includes('mode-rendered') ||
            row.canvas.parentClasses.indexOf('-cv-page-canvas') < 0 || !canvas ||
            !row.wrapperCenterInViewport) return {ok: false, reason: 'selected_canvas_not_ready', observation};
        selected.push({index, wrapper, canvas});
      }
      const native = [];
      let nativeReason = disabledReason || (!integrityOk() ? 'observer_integrity_lost' : null);
      if (!nativeReason) {
        try {
        for (const selectedRow of selected) {
          const candidate = candidates.get(selectedRow.canvas);
          const state = stateFor(selectedRow.canvas);
          const targetContext = contextFor(selectedRow.canvas);
          if (!candidate || candidate.target !== selectedRow.canvas || candidate.wrapper !== selectedRow.wrapper ||
              candidate.episodePath !== episodePath ||
              candidate.slot !== selectedRow.index ||
              candidate.total !== total || candidate.generation !== state.generation ||
              candidate.writes !== state.writes || candidate.targetWidth !== selectedRow.canvas.width ||
              candidate.targetHeight !== selectedRow.canvas.height || state.clipUnsafe ||
              selectedRow.canvas.parentElement?.classList.contains('-cv-page-canvas') !== true ||
              selectedRow.canvas.parentElement.querySelectorAll('canvas').length !== 1 ||
              !targetContext || ['width', 'height', 'getContext', 'toDataURL'].some(name =>
                Object.hasOwn(selectedRow.canvas, name)) ||
              trackedContextMethods.some(name => Object.hasOwn(targetContext, name)) ||
              contextStateProperties.some(name => Object.hasOwn(targetContext, name)) ||
              proofApiProperties.some(name => Object.hasOwn(targetContext, name)) ||
              targetContext.drawImage !== CanvasRenderingContext2D.prototype.drawImage ||
              !paintStillSupported(candidate.targetPaint)) {
            nativeReason = lastSources.get(selectedRow.canvas)?.supported === false
              ? 'native_source_dimensions_unsupported' : 'native_candidate_missing_or_stale';
            break;
          }
          const snapshotAttrs = contextAttributes(contextFor(candidate.snapshot));
          if (!attrsEqual(snapshotAttrs, candidate.snapshotAttributes) ||
              !validDimensions(candidate.sourceWidth, candidate.sourceHeight) ||
              candidate.snapshot.width !== candidate.sourceWidth ||
              candidate.snapshot.height !== candidate.sourceHeight) {
            nativeReason = 'native_snapshot_context_changed';
            break;
          }
          const targetAttributes = contextAttributes(targetContext);
          if (!attrsEqual(targetAttributes, candidate.targetPaint.attributes)) {
            nativeReason = 'target_context_changed';
            break;
          }
          const replay = document.createElement('canvas');
          replay.width = selectedRow.canvas.width;
          replay.height = selectedRow.canvas.height;
          const replayContext = Reflect.apply(nativeGetContext, replay, ['2d', copyOptions(targetAttributes)]);
          if (!replayContext) { nativeReason = 'replay_context_unavailable'; break; }
          configureReplay(replayContext, candidate);
          Reflect.apply(nativeDraw, replayContext, [candidate.snapshot, 0, 0,
            candidate.sourceWidth, candidate.sourceHeight,
            0, 0, replay.width, replay.height]);
          const replayPixels = pixels(replay);
          const targetPixels = pixels(selectedRow.canvas);
          if (!compare(replayPixels, targetPixels)) { nativeReason = 'native_replay_pixel_mismatch'; break; }
          const sourcePixels = pixels(candidate.snapshot);
          if (sourcePixels.length !== candidate.sourceWidth * candidate.sourceHeight * 4) {
            nativeReason = 'native_snapshot_dimensions_invalid'; break;
          }
          for (let offset = 3; offset < sourcePixels.length; offset += 4) {
            if (sourcePixels[offset] !== 255) { nativeReason = 'native_source_not_opaque'; break; }
          }
          if (nativeReason) break;
          native.push({selectedRow, candidate, targetPixels: new Uint8ClampedArray(targetPixels)});
        }
        } catch (_) {
          native.length = 0;
          nativeReason = 'native_validation_exception';
        }
      }
      let useNative = native.length === selected.length && !nativeReason;
      const images = [];
      try {
        if (useNative) {
          for (const item of native) {
            images.push({slot: item.selectedRow.index,
              width: item.candidate.sourceWidth, height: item.candidate.sourceHeight,
              png: pngDataUrl(item.candidate.snapshot)});
          }
        }
      } catch (_) {
        nativeReason = 'native_snapshot_readback_failed';
        useNative = false;
        images.length = 0;
      }
      if (!useNative) {
        // Display-canvas readback would change resolution; retain the failure instead.
        return {ok: false, reason: nativeReason, observation,
          source_dimensions: selected.map(item => ({slot: item.index,
            ...(lastSources.get(item.canvas) || {})}))};
      }
      let token = null;
      if (useNative) {
        if (proofs.size >= 1) proofs.clear();
        token = `h${nextProof++}`;
        proofs.set(token, {
          current, total, episodePath,
          collectedAt: performance.now(),
          viewport: observation.viewport,
          seek: observation.seek,
          wrapperCount: observation.slots.length,
          expectedSlots: expectedSlots.slice(),
          expectedBodySlots: expectedBodySlots.slice(),
          hasTopEmptyPage: observedTopEmpty,
          rows: native.map(item => ({
            target: item.selectedRow.canvas,
            wrapper: item.selectedRow.wrapper,
            slot: item.selectedRow.index,
            generation: item.candidate.generation,
            writes: item.candidate.writes,
            width: item.candidate.targetWidth,
            height: item.candidate.targetHeight,
            observation: observation.slots[item.selectedRow.index],
            pixels: item.targetPixels,
          })),
        });
      }
      for (const item of selected) candidates.delete(item.canvas);
      return {ok: true, mode: 'native', reason: null,
        token, observation, images};
    },
    release({token, expectedSlots, episodePath}) {
      if (typeof token === 'string') proofs.delete(token);
      const selected = new Set(Array.isArray(expectedSlots) ? expectedSlots : []);
      for (const [proofToken, proof] of proofs) {
        if (proof.episodePath === episodePath && proof.expectedSlots.length === selected.size &&
            proof.expectedSlots.every(slot => selected.has(slot))) proofs.delete(proofToken);
      }
      for (const [canvas, candidate] of candidates) {
        if (candidate.episodePath === episodePath && selected.has(candidate.slot)) candidates.delete(canvas);
      }
      return {candidateCount: candidates.size, proofCount: proofs.size};
    },
    verify(token) { return api.verifyDetailed(token).ok; },
    verifyDetailed(token) {
      const proof = proofs.get(token);
      proofs.delete(token);
      if (!proof) return {ok: false, reason: 'proof_missing'};
      if (!integrityOk()) return {ok: false, reason: 'observer_integrity_lost'};
      const observation = currentObservation();
      const elapsedMs = performance.now() - proof.collectedAt;
      const fail = reason => ({
        ok: false, reason, elapsed_ms: elapsedMs,
        expected: {current: proof.current, total: proof.total, viewport: proof.viewport,
          seek: proof.seek, wrapper_count: proof.wrapperCount,
          body_slots: proof.expectedBodySlots, selected_slots: proof.expectedSlots,
          has_top_empty_page: proof.hasTopEmptyPage},
        observed: {current: Number(observation.currentText), total: Number(observation.totalText),
          viewport: observation.viewport, seek: observation.seek,
          wrapper_count: observation.slots.length,
          body_slots: bodyLayout(observation),
          has_top_empty_page: observation.viewerClasses.includes('mode-has-top-emptypage'),
          document_ready_state: document.readyState},
        rows: proof.rows.map(row => {
          const wrapper = document.querySelector('#xCVPages')?.children[row.slot];
          const canvas = wrapper?.querySelector('canvas');
          const state = stateFor(row.target);
          let pixelComparison = 'not_compared';
          // Failure-only readback distinguishes a same-pixel redraw from changed content.
          // Never serialize pixels or read a replacement/other-sized canvas.
          if (canvas === row.target && canvas.width === row.width && canvas.height === row.height) {
            try { pixelComparison = compare(pixels(canvas), row.pixels) ? 'equal' : 'different'; }
            catch (_) { pixelComparison = 'unreadable'; }
          }
          return {slot: row.slot, same_wrapper: wrapper === row.wrapper, same_canvas: canvas === row.target,
            expected_generation: row.generation, observed_generation: state.generation,
            expected_writes: row.writes, observed_writes: state.writes,
            expected: row.observation, observed: observation.slots[row.slot] ?? null,
            pixel_comparison: pixelComparison};
        }),
      });
      if (location.pathname !== proof.episodePath || location.search || location.hash ||
          Number(observation.currentText) !== proof.current || Number(observation.totalText) !== proof.total)
        return fail('episode_or_counter_changed');
      const hasTopEmptyPage = observation.viewerClasses.includes('mode-has-top-emptypage');
      const currentBodySlots = bodyLayout(observation);
      if (currentBodySlots === null || hasTopEmptyPage !== proof.hasTopEmptyPage ||
          currentBodySlots.length !== proof.expectedBodySlots.length ||
          currentBodySlots.some((slot, index) => slot !== proof.expectedBodySlots[index]))
        return fail('body_layout_changed');
      if (observation.slots.length !== proof.wrapperCount || proof.rows.length !== proof.expectedSlots.length ||
          proof.rows.some((row, index) => row.slot !== proof.expectedSlots[index]))
        return fail('wrapper_or_proof_slots_changed');
      const active = [];
      for (const index of proof.expectedBodySlots) {
        const row = observation.slots[index];
        if (row?.wrapperCenterInViewport) active.push(index);
      }
      if (active.length !== proof.expectedSlots.length ||
          active.some((value, index) => value !== proof.expectedSlots[index]))
        return fail('active_slots_changed');
      for (const row of proof.rows) {
        const wrapper = document.querySelector('#xCVPages')?.children[row.slot];
        const canvas = wrapper?.querySelector('canvas');
        const state = stateFor(row.target);
        const observed = observation.slots[row.slot];
        if (wrapper !== row.wrapper) return fail('wrapper_replaced');
        if (canvas !== row.target) return fail('canvas_replaced');
        if (state.generation !== row.generation) return fail('canvas_generation_changed');
        if (state.writes !== row.writes) return fail('canvas_writes_changed');
        if (canvas.width !== row.width || canvas.height !== row.height) return fail('canvas_dimensions_changed');
        if (!observed?.canvas?.ready || !observed.canvas.visible || !observed.wrapperCenterInViewport ||
            !observed.classes.includes('mode-loaded') || !observed.classes.includes('mode-rendered'))
          return fail('canvas_readiness_or_visibility_changed');
        let currentPixels;
        try { currentPixels = pixels(canvas); } catch (_) { return fail('canvas_pixels_unreadable'); }
        if (!compare(currentPixels, row.pixels)) return fail('canvas_pixels_changed');
      }
      return {ok: true, reason: null, elapsed_ms: elapsedMs};
    },
    clear() { candidates.clear(); proofs.clear(); disabledReason = 'capture_cache_cleared'; },
    status() { return {candidateCount: candidates.size, proofCount: proofs.size,
      disabledReason, integrity: integrityOk()}; },
  };
  window.__hanayumeNativeCapture = api;
  addEventListener('pagehide', () => { candidates.clear(); proofs.clear(); }, {once: true});
})()""".replace("__MAX_NATIVE_SIDE__", str(MAX_NATIVE_SIDE)).replace(
    "__MAX_NATIVE_PIXELS__", str(MAX_NATIVE_PIXELS)
).replace("__MAX_CANDIDATES__", str(MAX_CANDIDATES)).replace(
    "__MAX_CACHED_SOURCE_PIXELS__", str(MAX_CACHED_SOURCE_PIXELS)
)


COLLECT_CAPTURE_SCRIPT = r"""args => {
  const api = window.__hanayumeNativeCapture;
  if (!api || typeof api.collect !== 'function') return {ok: false, reason: 'capture_observer_missing'};
  return api.collect(args);
}"""


VERIFY_CAPTURE_SCRIPT = r"""token => {
  const api = window.__hanayumeNativeCapture;
  if (!api || typeof api.verifyDetailed !== 'function')
    return {ok: false, reason: 'capture_observer_missing'};
  return api.verifyDetailed(token);
}"""


RELEASE_CAPTURE_SCRIPT = r"""args => {
  const api = window.__hanayumeNativeCapture;
  if (!api || typeof api.release !== 'function') return null;
  return api.release(args);
}"""


@dataclass(frozen=True, slots=True)
class NativeImage:
    slot: int
    width: int
    height: int
    png: bytes


def decode_capture_images(
    value: object, *, expected_slots: tuple[int, ...], require_opaque: bool
) -> tuple[NativeImage, ...]:
    if not isinstance(value, list) or len(value) != len(expected_slots):
        raise UnknownPageStateError("Hanayume capture image list is incomplete")
    images: list[NativeImage] = []
    for expected, item in zip(expected_slots, value, strict=True):
        if not isinstance(item, dict) or item.get("slot") != expected:
            raise UnknownPageStateError("Hanayume capture image order changed")
        width, height, encoded = item.get("width"), item.get("height"), item.get("png")
        if not isinstance(width, int) or not isinstance(height, int) or width <= 0 or height <= 0:
            raise UnknownPageStateError("Hanayume capture image dimensions are invalid")
        if require_opaque and not valid_native_dimensions(width, height):
            raise UnknownPageStateError("Hanayume native source dimensions exceed the capture limits")
        prefix = "data:image/png;base64,"
        if (
            not isinstance(encoded, str)
            or not encoded.startswith(prefix)
            or len(encoded) > len(prefix) + 4 * ((MAX_IMAGE_BYTES + 2) // 3)
        ):
            raise UnknownPageStateError("Hanayume PNG readback failed")
        try:
            data = base64.b64decode(encoded.partition(",")[2], validate=True)
        except (binascii.Error, ValueError) as exc:
            raise UnknownPageStateError("Hanayume PNG data is malformed") from exc
        if not _valid_png(data, width=width, height=height, require_opaque=require_opaque):
            raise UnknownPageStateError("Hanayume PNG format or dimensions are invalid")
        images.append(NativeImage(expected, width, height, data))
    return tuple(images)


def _valid_png(data: bytes, *, width: int, height: int, require_opaque: bool) -> bool:
    if len(data) > MAX_IMAGE_BYTES or not data.startswith(b"\x89PNG\r\n\x1a\n"):
        return False
    try:
        with Image.open(io.BytesIO(data)) as image:
            if image.format != "PNG" or image.size != (width, height) or getattr(image, "n_frames", 1) != 1:
                return False
            image.verify()
        with Image.open(io.BytesIO(data)) as image:
            image.load()
            return not require_opaque or image.convert("RGBA").getchannel("A").getextrema() == (255, 255)
    except (OSError, ValueError, UnidentifiedImageError):
        return False


def encode_native_webp(images: tuple[NativeImage, ...]) -> tuple[CaptureResult, ...]:
    """Encode verified opaque source PNGs as method-4 lossless VP8L WebP."""

    if not features.check("webp"):
        return tuple(_png_result(item) for item in images)
    results: list[CaptureResult] = []
    for item in images:
        fallback = _png_result(item)
        try:
            with Image.open(io.BytesIO(item.png)) as image:
                if image.format != "PNG" or image.size != (item.width, item.height):
                    results.append(fallback)
                    continue
                original = image.convert("RGBA")
                if original.getchannel("A").getextrema() != (255, 255):
                    results.append(fallback)
                    continue
            output = io.BytesIO()
            original.save(output, format="WEBP", lossless=True, method=4)
            encoded = output.getvalue()
            if len(encoded) > MAX_IMAGE_BYTES or not _single_vp8l(encoded, width=item.width, height=item.height):
                results.append(fallback)
                continue
            with Image.open(io.BytesIO(encoded)) as decoded:
                if decoded.format != "WEBP" or decoded.size != (item.width, item.height) or getattr(decoded, "n_frames", 1) != 1:
                    results.append(fallback)
                    continue
                decoded.load()
                if decoded.convert("RGBA").tobytes() != original.tobytes():
                    results.append(fallback)
                    continue
            results.append(CaptureResult(encoded, item.width, item.height, "image/webp", ".webp"))
        except Exception:  # noqa: BLE001 - encoding failure keeps the validated source PNG
            results.append(fallback)
    return tuple(results)


def _png_result(item: NativeImage) -> CaptureResult:
    return CaptureResult(item.png, item.width, item.height, "image/png", ".png")


def _single_vp8l(data: bytes, *, width: int, height: int) -> bool:
    if (len(data) < 25 or data[:4] != b"RIFF" or int.from_bytes(data[4:8], "little") != len(data) - 8 or
            data[8:12] != b"WEBP" or data[12:16] != b"VP8L"):
        return False
    chunk_size = int.from_bytes(data[16:20], "little")
    end = 20 + chunk_size
    if chunk_size < 5 or end + (chunk_size & 1) != len(data) or data[20] != 0x2F:
        return False
    encoded_width = 1 + data[21] + ((data[22] & 0x3F) << 8)
    encoded_height = 1 + (data[22] >> 6) + (data[23] << 2) + ((data[24] & 0x0F) << 10)
    alpha = (data[24] >> 4) & 1
    version = data[24] >> 5
    return encoded_width == width and encoded_height == height and alpha == 0 and version == 0
