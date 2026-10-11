"""Strict Younganimal viewer snapshots and rendered-canvas PNG readback."""

from __future__ import annotations

import base64
import binascii
import hashlib
import io
from dataclasses import dataclass

from PIL import Image, UnidentifiedImageError

from screenshot_crawler.core.capture import CaptureResult
from screenshot_crawler.core.errors import UnknownPageStateError

MAX_PNG_BYTES = 8_000_000

OBSERVER_INIT_SCRIPT = r"""(() => {
  if (window.__younganimalViewerCapture) return;
  const nodeIds = new WeakMap();
  const canvasStates = new WeakMap();
  let nextNodeId = 1;
  let domGeneration = 0;
  let captureDomGeneration = 0;
  const nodeId = node => {
    if (!node) return null;
    if (!nodeIds.has(node)) nodeIds.set(node, nextNodeId++);
    return nodeIds.get(node);
  };
  const stateFor = canvas => {
    let state = canvasStates.get(canvas);
    if (!state) {
      state = {generation: 0, writes: 0};
      canvasStates.set(canvas, state);
      canvas.addEventListener('contextlost', () => {
        state.generation += 1;
        state.writes += 1;
      });
      canvas.addEventListener('contextrestored', () => {
        state.generation += 1;
        state.writes += 1;
      });
    }
    return state;
  };
  const contextPrototype = CanvasRenderingContext2D.prototype;
  const nativeDrawImage = contextPrototype.drawImage;
  const nativeGetContext = HTMLCanvasElement.prototype.getContext;
  const nativeGetImageData = contextPrototype.getImageData;
  const nativeToDataURL = HTMLCanvasElement.prototype.toDataURL;
  const nativeGetAttribute = Element.prototype.getAttribute;
  const nativeGetContextAttributes = contextPrototype.getContextAttributes;
  const nativeGetTransform = contextPrototype.getTransform;
  const nativeSetTransform = contextPrototype.setTransform;
  const originals = new Map();
  const wrapped = new Map();
  const drawObservers = new Set();
  const notifyDrawObservers = event => {
    for (const callback of [...drawObservers]) {
      try { callback(event); } catch (_) { /* Observers must not change reader rendering. */ }
    }
  };
  for (const name of ['fillRect', 'strokeRect', 'clearRect', 'fill', 'stroke',
                       'fillText', 'strokeText', 'putImageData', 'drawImage', 'reset', 'clip']) {
    const original = contextPrototype[name];
    if (typeof original !== 'function') continue;
    const replacement = function(...args) {
      const target = this.canvas instanceof HTMLCanvasElement ? this.canvas : null;
      const state = target ? stateFor(target) : null;
      if (name === 'drawImage' && target) {
        notifyDrawObservers({phase: 'before', method: name, context: this, target,
          source: args[0], drawArgs: args.slice(1), state: {generation: state.generation, writes: state.writes}});
      }
      let result;
      try { result = Reflect.apply(original, this, args); }
      catch (error) {
        if (target) notifyDrawObservers({phase: 'failed', method: name, context: this, target,
          source: args[0], drawArgs: args.slice(1), state: {generation: state.generation, writes: state.writes}});
        throw error;
      }
      if (target) {
        if (name === 'reset') state.generation += 1;
        state.writes += 1;
        notifyDrawObservers({phase: 'after', method: name, context: this, target,
          source: args[0], drawArgs: args.slice(1), state: {generation: state.generation, writes: state.writes}});
      }
      return result;
    };
    originals.set(name, original);
    wrapped.set(name, replacement);
    Object.defineProperty(contextPrototype, name, {
      configurable: true, enumerable: false, writable: true, value: replacement,
    });
  }
  const widthDescriptor = Object.getOwnPropertyDescriptor(HTMLCanvasElement.prototype, 'width');
  const heightDescriptor = Object.getOwnPropertyDescriptor(HTMLCanvasElement.prototype, 'height');
  const dimensionDescriptors = new Map();
  const integrityChecks = [];
  const attributeOwners = new WeakMap();
  const noteDimensionAttribute = (canvas, attributeName) => {
    if (!(canvas instanceof HTMLCanvasElement) || !['width', 'height'].includes(String(attributeName).toLowerCase())) return;
    const state = stateFor(canvas);
    state.generation += 1;
    state.writes += 1;
  };
  for (const [name, descriptor] of [['width', widthDescriptor], ['height', heightDescriptor]]) {
    if (!descriptor?.get || !descriptor?.set) continue;
    const replacement = {
      configurable: descriptor.configurable,
      enumerable: descriptor.enumerable,
      get: descriptor.get,
      set(value) {
        Reflect.apply(descriptor.set, this, [value]);
        if (this instanceof HTMLCanvasElement) {
          const state = stateFor(this);
          state.generation += 1;
          state.writes += 1;
        }
      },
    };
    dimensionDescriptors.set(name, replacement);
    Object.defineProperty(HTMLCanvasElement.prototype, name, replacement);
  }
  for (const name of ['setAttribute', 'setAttributeNS', 'removeAttribute', 'removeAttributeNS',
                      'setAttributeNode', 'setAttributeNodeNS', 'removeAttributeNode']) {
    const original = Element.prototype[name];
    if (typeof original !== 'function') continue;
    const replacement = function(...args) {
      const attributeName = name.includes('AttributeNode') ? args[0]?.name || ''
        : name.endsWith('NS') ? args[1] || '' : args[0] || '';
      const result = Reflect.apply(original, this, args);
      noteDimensionAttribute(this, attributeName);
      return result;
    };
    Object.defineProperty(Element.prototype, name, {
      configurable: true, enumerable: false, writable: true, value: replacement,
    });
    integrityChecks.push(() => Element.prototype[name] === replacement);
  }
  const attributesDescriptor = Object.getOwnPropertyDescriptor(Element.prototype, 'attributes');
  if (attributesDescriptor?.get) {
    const originalGet = attributesDescriptor.get;
    const replacementGet = function() {
      const value = Reflect.apply(originalGet, this, []);
      if (this instanceof HTMLCanvasElement && value) attributeOwners.set(value, this);
      return value;
    };
    Object.defineProperty(Element.prototype, 'attributes', {
      configurable: attributesDescriptor.configurable,
      enumerable: attributesDescriptor.enumerable,
      get: replacementGet,
    });
    integrityChecks.push(() => Object.getOwnPropertyDescriptor(Element.prototype, 'attributes')?.get === replacementGet);
  }
  for (const name of ['setNamedItem', 'setNamedItemNS', 'removeNamedItem', 'removeNamedItemNS']) {
    const original = NamedNodeMap.prototype[name];
    if (typeof original !== 'function') continue;
    const replacement = function(...args) {
      const canvas = attributeOwners.get(this);
      const attributeName = name.startsWith('set')
        ? args[0]?.name || args[0]?.nodeName || ''
        : name.endsWith('NS') ? args[1] || '' : args[0] || '';
      const result = Reflect.apply(original, this, args);
      noteDimensionAttribute(canvas, attributeName);
      return result;
    };
    Object.defineProperty(NamedNodeMap.prototype, name, {
      configurable: true, enumerable: false, writable: true, value: replacement,
    });
    integrityChecks.push(() => NamedNodeMap.prototype[name] === replacement);
  }
  const attrValueDescriptor = Object.getOwnPropertyDescriptor(Attr.prototype, 'value');
  if (attrValueDescriptor?.get && attrValueDescriptor?.set) {
    const originalGet = attrValueDescriptor.get;
    const originalSet = attrValueDescriptor.set;
    const replacementGet = function() { return Reflect.apply(originalGet, this, []); };
    const replacementSet = function(value) {
      const owner = this.ownerElement;
      const attributeName = this.name;
      Reflect.apply(originalSet, this, [value]);
      noteDimensionAttribute(owner, attributeName);
    };
    Object.defineProperty(Attr.prototype, 'value', {
      configurable: attrValueDescriptor.configurable,
      enumerable: attrValueDescriptor.enumerable,
      get: replacementGet,
      set: replacementSet,
    });
    integrityChecks.push(() => {
      const current = Object.getOwnPropertyDescriptor(Attr.prototype, 'value');
      return current?.get === replacementGet && current?.set === replacementSet;
    });
  }
  let observedRoot = null;
  const MAX_MUTATION_JOURNAL = 64;
  const SAFE_CLASS_FLAGS = new Set([
    '-cv', '-cv-page', '-cv-page-canvas', '-cv-splash', 'mode-dir-rtl',
    'mode-ci-page', 'mode-empty', 'mode-first-page', 'mode-good', 'mode-h', 'mode-has-top-emptypage',
    'mode-hide', 'mode-last', 'mode-last-page', 'mode-lang-ja', 'mode-loaded',
    'mode-loading', 'mode-nav-dir-rtl', 'mode-nav-open', 'mode-pr', 'mode-req-render',
    'mode-pr-page', 'mode-rendered', 'mode-scroll-bottom', 'mode-spread', 'mode-top-pr', 'mode-top-pr-page', 'mode-ci', 'mode-lang-ja',
  ]);
  const SAFE_TAGS = new Set(['CANVAS', 'DIV', 'INPUT', 'SECTION', 'SPAN', 'SVG']);
  const CANONICAL_CI_CLASSES = new Set(['-cv-page', 'mode-ci']);
  const CANONICAL_CI_SCROLL_PARENT_CLASSES = new Set(['-cv-ci', '-cv-page-content']);
  const CANONICAL_CI_SCROLL_BASE_CLASSES = new Set(['-cv-ci-content']);
  const CANONICAL_CI_SCROLL_BOTTOM_CLASSES = new Set(['-cv-ci-content', 'mode-scroll-bottom']);
  const CANONICAL_LEAD_CLASSES = new Set(['-cv-page', 'mode-empty', 'mode-pr', 'mode-top-pr']);
  const CANONICAL_TOP_EMPTY_CLASSES = new Set(['-cv-page', 'mode-empty']);
  const CANONICAL_CI_TAIL = [
    new Set(['-cv-page', 'mode-empty', 'mode-pr']),
    new Set(['-cv-page', 'mode-empty', 'mode-pr']),
    new Set(['-cv-page', 'mode-good']),
    new Set(['-cv-page', 'mode-last']),
  ];
  const mutationJournal = [];
  let droppedMutationCount = 0;
  let unrecordedMutationCount = 0;
  let mutationCoverageLost = false;
  const safeClassFlags = value => typeof value === 'string'
    ? value.split(/\s+/).filter(name => SAFE_CLASS_FLAGS.has(name)).sort() : [];
  const classTokenSet = value => typeof value === 'string'
    ? new Set(value.split(/[\t\n\f\r ]+/).filter(Boolean)) : null;
  const tokenSetsEqual = (left, right) => !!left && !!right && left.size === right.size &&
    [...left].every(token => right.has(token));
  const canonicalCiWrapper = () => {
    const viewers = [...document.querySelectorAll('#comici-viewer')];
    const pageRoots = [...document.querySelectorAll('#xCVPages')];
    if (viewers.length !== 1 || pageRoots.length !== 1 || !viewers[0].contains(pageRoots[0])) return null;
    const viewer = viewers[0];
    const pages = pageRoots[0];
    const children = [...pages.children];
    const ciIndex = children.length - 5;
    const topEmpty = viewer.classList.contains('mode-has-top-emptypage');
    const bodyStart = topEmpty ? 2 : 1;
    if (children.length < 9 || ciIndex <= bodyStart ||
        !['mode-spread', 'mode-dir-rtl', 'mode-nav-dir-rtl'].every(name => viewer.classList.contains(name)) ||
        viewer.classList.contains('mode-last-page') ||
        !tokenSetsEqual(classTokenSet(Reflect.apply(nativeGetAttribute, children[0], ['class'])), CANONICAL_LEAD_CLASSES) ||
        children[0].querySelectorAll('canvas').length !== 0 ||
        tokenSetsEqual(classTokenSet(Reflect.apply(nativeGetAttribute, children[ciIndex], ['class'])), CANONICAL_CI_CLASSES) === false ||
        children[ciIndex].querySelectorAll('canvas').length !== 0) return null;
    if (topEmpty && (!tokenSetsEqual(
        classTokenSet(Reflect.apply(nativeGetAttribute, children[1], ['class'])), CANONICAL_TOP_EMPTY_CLASSES
      ) || children[1].querySelectorAll('canvas').length !== 0)) return null;
    for (let offset = 0; offset < CANONICAL_CI_TAIL.length; offset += 1) {
      const tail = children[ciIndex + 1 + offset];
      const tokens = classTokenSet(Reflect.apply(nativeGetAttribute, tail, ['class']));
      if (!tokenSetsEqual(tokens, CANONICAL_CI_TAIL[offset]) || tail.querySelectorAll('canvas').length !== 0) return null;
    }
    return children[ciIndex] instanceof Element ? children[ciIndex] : null;
  };
  const fullyOutsideViewport = node => {
    if (!(node instanceof Element)) return false;
    const rect = node.getBoundingClientRect();
    if (![rect.x, rect.y, rect.width, rect.height].every(Number.isFinite) ||
        rect.width <= 0 || rect.height <= 0) return false;
    return rect.right <= 0 || rect.bottom <= 0 || rect.left >= innerWidth || rect.top >= innerHeight;
  };
  const rawRect = node => {
    if (!(node instanceof Element)) return null;
    const rect = node.getBoundingClientRect();
    return [rect.x, rect.y, rect.width, rect.height].every(Number.isFinite) &&
      rect.width > 0 && rect.height > 0
      ? [rect.x, rect.y, rect.width, rect.height] : null;
  };
  const rectsDisjoint = (left, right) => Array.isArray(left) && Array.isArray(right) &&
    left.length === 4 && right.length === 4 &&
    (left[0] + left[2] <= right[0] || right[0] + right[2] <= left[0] ||
     left[1] + left[3] <= right[1] || right[1] + right[3] <= left[1]);
  const rectContains = (outer, inner) => Array.isArray(outer) && Array.isArray(inner) &&
    outer.length === 4 && inner.length === 4 &&
    inner[0] >= outer[0] && inner[1] >= outer[1] &&
    inner[0] + inner[2] <= outer[0] + outer[2] &&
    inner[1] + inner[3] <= outer[1] + outer[3];
  const activeBodyGeometry = ciWrapper => {
    const viewers = [...document.querySelectorAll('#comici-viewer')];
    const pageRoots = [...document.querySelectorAll('#xCVPages')];
    const seekBars = [...document.querySelectorAll('#xCVSeekBar')];
    if (viewers.length !== 1 || pageRoots.length !== 1 || seekBars.length !== 1) return null;
    const viewer = viewers[0], pages = pageRoots[0], seek = seekBars[0];
    if (!viewer.contains(pages) || !viewer.contains(seek) || seek.type !== 'range' || seek.disabled ||
        canonicalCiWrapper() !== ciWrapper) return null;
    const children = [...pages.children];
    const topEmpty = viewer.classList.contains('mode-has-top-emptypage');
    const bodyStart = topEmpty ? 2 : 1;
    const ciIndex = children.length - 5;
    const min = Number(seek.min), max = Number(seek.max), step = Number(seek.step), value = Number(seek.value);
    if (ciIndex <= bodyStart || min !== 1 || step !== 2 ||
        max !== (topEmpty ? children.length : children.length - 1) ||
        !Number.isInteger(value) || value < min || value > max || (max - value) % step !== 0 ||
        viewer.classList.contains('mode-last-page')) return null;
    const allowedBodyClasses = [
      ['-cv-page'], ['-cv-page', 'mode-loading'],
      ['-cv-page', 'mode-loading', 'mode-req-render'], ['-cv-page', 'mode-loaded'],
      ['-cv-page', 'mode-loaded', 'mode-rendered'],
    ];
    for (let slot = bodyStart; slot < ciIndex; slot += 1) {
      const wrapper = children[slot];
      if (!wrapper || wrapper.parentElement !== pages ||
          !allowedBodyClasses.some(expected => tokenSetsEqual(
            classTokenSet(Reflect.apply(nativeGetAttribute, wrapper, ['class'])), new Set(expected)))) return null;
    }
    const focus = max - value + 1;
    const activeSlots = [focus - 1, focus].filter(slot => slot >= bodyStart && slot < ciIndex);
    if (!activeSlots.length || activeSlots.length > 2) return null;
    const rows = [];
    for (const slot of activeSlots) {
      const wrapper = children[slot];
      const canvases = [...wrapper.querySelectorAll('canvas')];
      if (canvases.length !== 1) return null;
      const canvas = canvases[0];
      const holder = canvas.parentElement;
      if (!holder || holder.closest('.-cv-page') !== wrapper || !wrapper.contains(holder) ||
          !holder.classList.contains('-cv-page-canvas') || holder.querySelectorAll('canvas').length !== 1 ||
          !Number.isSafeInteger(canvas.width) || !Number.isSafeInteger(canvas.height) ||
          canvas.width <= 0 || canvas.height <= 0) return null;
      const wrapperRect = rawRect(wrapper);
      const canvasRect = rawRect(canvas);
      if (!wrapperRect || !canvasRect) return null;
      rows.push({wrapperRect, canvasRect});
    }
    return rows;
  };
  const safeCiScrollMutationGeometry = (target, ciWrapper) => {
    const targetRect = rawRect(target);
    const ciRect = rawRect(ciWrapper);
    const activeRows = activeBodyGeometry(ciWrapper);
    if (!targetRect || !ciRect || !activeRows) return false;
    // Preserve the previously verified offscreen case while requiring a fresh
    // strict body/seek map even when that shortcut applies.
    if (fullyOutsideViewport(target) && fullyOutsideViewport(ciWrapper)) return true;
    const bodyRects = activeRows.flatMap(row => [row.wrapperRect, row.canvasRect]);
    const bothRectsDisjoint = bodyRects.every(bodyRect =>
      rectsDisjoint(targetRect, bodyRect) && rectsDisjoint(ciRect, bodyRect));
    const targetContained = rectContains(ciRect, targetRect);
    const ciDisjoint = bodyRects.every(bodyRect => rectsDisjoint(ciRect, bodyRect));
    return bothRectsDisjoint || (targetContained && ciDisjoint);
  };
  const isCanonicalCiScrollTarget = (target, ciWrapper) => {
    if (!(target instanceof Element) || target === ciWrapper || target.tagName !== 'DIV' ||
        !(ciWrapper instanceof Element) || !ciWrapper.contains(target) || target.querySelectorAll('canvas').length !== 0)
      return false;
    const parent = target.parentElement;
    if (!(parent instanceof Element) || parent.tagName !== 'DIV' || parent.parentElement !== ciWrapper ||
        parent.children.length !== 1 || parent.firstElementChild !== target ||
        !tokenSetsEqual(classTokenSet(Reflect.apply(nativeGetAttribute, parent, ['class'])),
          CANONICAL_CI_SCROLL_PARENT_CLASSES)) return false;
    const pages = ciWrapper.parentElement;
    const viewer = pages?.parentElement;
    const bodyStart = viewer instanceof Element && viewer.classList.contains('mode-has-top-emptypage') ? 2 : 1;
    const ciIndex = pages ? [...pages.children].indexOf(ciWrapper) : -1;
    if (!pages || !viewer || !pages.contains(ciWrapper) || ciIndex <= bodyStart) return false;
    return true;
  };
  const classifyCaptureMutation = (record, batch, index, ciWrapper) => {
    const namespace = record?.attributeNamespace;
    const ordinaryNamespace = namespace === null;
    const isClass = record?.type === 'attributes' && record.attributeName === 'class' && ordinaryNamespace;
    const canonicalCi = isClass && record.target === ciWrapper;
    const ciScrollTarget = isClass && isCanonicalCiScrollTarget(record.target, ciWrapper);
    const result = {namespacePresent: !ordinaryNamespace,
      canonicalCiWrapper: isClass ? canonicalCi : null,
      ciScrollWidgetTarget: isClass ? ciScrollTarget : null,
      classTokenSetsSame: null, canonicalCiClassNoop: false, ciScrollWidgetClassNoop: false};
    if ((!canonicalCi && !ciScrollTarget) || typeof record.oldValue !== 'string') return result;
    let newValue = null;
    let reconstructed = false;
    for (let next = index + 1; next < batch.length; next += 1) {
      const candidate = batch[next];
      if (candidate.type === 'attributes' && candidate.target === record.target &&
          candidate.attributeName === 'class' && candidate.attributeNamespace === namespace) {
        if (typeof candidate.oldValue !== 'string') return result;
        newValue = candidate.oldValue;
        reconstructed = true;
        break;
      }
    }
    if (!reconstructed) {
      newValue = Reflect.apply(nativeGetAttribute, record.target, ['class']);
      if (typeof newValue !== 'string') return result;
    }
    const oldTokens = classTokenSet(record.oldValue);
    const newTokens = classTokenSet(newValue);
    result.classTokenSetsSame = tokenSetsEqual(oldTokens, newTokens);
    if (canonicalCi) {
      result.canonicalCiClassNoop = tokenSetsEqual(oldTokens, CANONICAL_CI_CLASSES) &&
        tokenSetsEqual(newTokens, CANONICAL_CI_CLASSES);
    }
    if (ciScrollTarget) {
      const oldBase = tokenSetsEqual(oldTokens, CANONICAL_CI_SCROLL_BASE_CLASSES);
      const oldScroll = tokenSetsEqual(oldTokens, CANONICAL_CI_SCROLL_BOTTOM_CLASSES);
      const newBase = tokenSetsEqual(newTokens, CANONICAL_CI_SCROLL_BASE_CLASSES);
      const newScroll = tokenSetsEqual(newTokens, CANONICAL_CI_SCROLL_BOTTOM_CLASSES);
      result.ciScrollWidgetClassNoop = (oldBase && newBase) || (oldScroll && newScroll) ||
        (oldBase && newScroll && safeCiScrollMutationGeometry(record.target, ciWrapper));
    }
    return result;
  };
  const mutationArea = node => {
    const viewer = document.querySelector('#comici-viewer');
    const pages = document.querySelector('#xCVPages');
    const seek = document.querySelector('#xCVSeekBar');
    if (node === viewer) return 'viewer';
    if (node === pages) return 'pages';
    if (node === seek) return 'seek';
    const wrapper = node instanceof Element
      ? (node.matches('.-cv-page') ? node : node.closest('.-cv-page')) : null;
    if (wrapper && wrapper.parentElement === pages) return node === wrapper ? 'wrapper' : 'wrapper_descendant';
    if (node instanceof Element && node.closest('#xCVPages')) return 'pages_descendant';
    return 'viewer_descendant';
  };
  const mutationSlot = node => {
    const pages = document.querySelector('#xCVPages');
    if (!(node instanceof Element)) return null;
    const wrapper = node.matches('.-cv-page') ? node : node.closest('.-cv-page');
    return wrapper?.parentElement === pages ? [...pages.children].indexOf(wrapper) : null;
  };
  const summarizeMutationNode = node => {
    const tagName = node instanceof Element ? node.tagName : '';
    return {
      node: nodeId(node),
      area: mutationArea(node),
      slot: mutationSlot(node),
      tag: SAFE_TAGS.has(tagName) ? tagName : 'OTHER',
      classFlags: node instanceof Element ? safeClassFlags(node.getAttribute('class')) : [],
    };
  };
  const appendMutationRecord = (record, batch, index, generation, captureMetadata) => {
    const target = record.target;
    const summary = {
      generation,
      captureGeneration: captureMetadata.captureGeneration,
      kind: record.type === 'attributes' ? 'attributes' : 'childList',
      targetArea: mutationArea(target),
      targetNode: nodeId(target),
      slot: mutationSlot(target),
      attributeName: null,
      namespacePresent: false,
      changed: null,
      sameAssignment: null,
      canonicalCiWrapper: captureMetadata.canonicalCiWrapper,
      ciScrollWidgetTarget: captureMetadata.ciScrollWidgetTarget,
      classTokenSetsSame: captureMetadata.classTokenSetsSame,
      canonicalCiClassNoop: captureMetadata.canonicalCiClassNoop,
      ciScrollWidgetClassNoop: captureMetadata.ciScrollWidgetClassNoop,
      classAdded: [],
      classRemoved: [],
      addedCount: 0,
      removedCount: 0,
      added: [],
      removed: [],
    };
    if (record.type === 'attributes') {
      summary.namespacePresent = record.attributeNamespace !== null;
      summary.attributeName = record.attributeName === 'class' || record.attributeName === 'id'
        ? record.attributeName : 'other';
      // Missing or non-null namespaces are unknown here. Do not let a
      // namespaced local name such as "class" read or inherit the ordinary
      // unnamespaced attribute's value.
      if (record.attributeNamespace === null) {
        const oldValue = typeof record.oldValue === 'string' ? record.oldValue : '';
        let newValue = target instanceof Element ? target.getAttribute(record.attributeName) || '' : '';
        for (let next = index + 1; next < batch.length; next += 1) {
          const candidate = batch[next];
          if (candidate.type === 'attributes' && candidate.target === target &&
              candidate.attributeName === record.attributeName &&
              candidate.attributeNamespace === record.attributeNamespace) {
            newValue = typeof candidate.oldValue === 'string' ? candidate.oldValue : '';
            break;
          }
        }
        summary.changed = oldValue !== newValue;
        summary.sameAssignment = oldValue === newValue;
        if (record.attributeName === 'class') {
          const oldFlags = new Set(safeClassFlags(oldValue));
          const newFlags = new Set(safeClassFlags(newValue));
          summary.classAdded = [...newFlags].filter(name => !oldFlags.has(name)).sort();
          summary.classRemoved = [...oldFlags].filter(name => !newFlags.has(name)).sort();
        }
      }
    } else {
      const added = [...record.addedNodes];
      const removed = [...record.removedNodes];
      summary.addedCount = added.length;
      summary.removedCount = removed.length;
      summary.added = added.slice(0, 4).map(summarizeMutationNode);
      summary.removed = removed.slice(0, 4).map(summarizeMutationNode);
    }
    mutationJournal.push(summary);
    if (mutationJournal.length > MAX_MUTATION_JOURNAL) {
      mutationJournal.shift();
      droppedMutationCount += 1;
    }
  };
  const observer = new MutationObserver(records => {
    const firstGeneration = domGeneration + 1;
    domGeneration += records.length;
    let ciWrapper = null;
    try { ciWrapper = canonicalCiWrapper(); } catch (_) { /* unknown role means count every record */ }
    const semantics = records.map((record, index) => {
      try { return classifyCaptureMutation(record, records, index, ciWrapper); }
      catch (_) {
        return {canonicalCiWrapper: null, classTokenSetsSame: null, canonicalCiClassNoop: false};
      }
    });
    let captureGeneration = captureDomGeneration;
    const captureMetadata = semantics.map(semantic => {
      if (!semantic.canonicalCiClassNoop && !semantic.ciScrollWidgetClassNoop) captureGeneration += 1;
      return {...semantic, captureGeneration};
    });
    captureDomGeneration = captureGeneration;
    for (let index = 0; index < records.length; index += 1) {
      try {
        appendMutationRecord(records[index], records, index, firstGeneration + index, captureMetadata[index]);
      } catch (_) {
        mutationCoverageLost = true;
        unrecordedMutationCount += 1;
      }
    }
  });
  const refreshObservedRoot = () => {
    const viewer = document.querySelector('#comici-viewer');
    if (viewer === observedRoot) return;
    observer.disconnect();
    observedRoot = viewer;
    if (viewer) observer.observe(viewer, {
      attributes: true, childList: true, subtree: true,
      attributeFilter: ['class', 'id'], attributeOldValue: true,
    });
  };
  const pixelHash = canvas => {
    const context = canvas.getContext('2d', {willReadFrequently: true});
    if (!context) throw new Error('canvas_context_missing');
    const bytes = context.getImageData(0, 0, canvas.width, canvas.height).data;
    let first = 2166136261;
    let second = 0x9e3779b9;
    for (let index = 0; index < bytes.length; index += 1) {
      const byte = bytes[index];
      first = Math.imul(first ^ byte, 16777619);
      second = Math.imul(second + byte + (index & 255), 2246822519);
    }
    return `${(first >>> 0).toString(16).padStart(8, '0')}:${(second >>> 0).toString(16).padStart(8, '0')}`;
  };
  const inspect = (pixelSlots = []) => {
    refreshObservedRoot();
    const one = selector => {
      const nodes = [...document.querySelectorAll(selector)];
      return nodes.length === 1 ? nodes[0] : null;
    };
    const viewer = one('#comici-viewer');
    const pages = one('#xCVPages');
    const seek = one('#xCVSeekBar');
    const viewport = {width: innerWidth, height: innerHeight, dpr: devicePixelRatio};
    const pixelSet = new Set(pixelSlots);
    const slots = pages ? [...pages.children].map((wrapper, index) => {
      const classes = [...wrapper.classList].sort();
      const canvases = [...wrapper.querySelectorAll('canvas')];
      const canvas = canvases.length === 1 ? canvases[0] : null;
      const rect = wrapper.getBoundingClientRect();
      const centerInViewport = rect.width > 0 && rect.height > 0 &&
        rect.x + rect.width / 2 >= 0 && rect.x + rect.width / 2 <= innerWidth &&
        rect.y + rect.height / 2 >= 0 && rect.y + rect.height / 2 <= innerHeight;
      const canvasRect = canvas?.getBoundingClientRect();
      const canvasVisible = !!canvasRect && canvasRect.width > 0 && canvasRect.height > 0 &&
        canvasRect.x >= -1 && canvasRect.y >= -1 &&
        canvasRect.right <= innerWidth + 1 && canvasRect.bottom <= innerHeight + 1;
      const parentClasses = canvas?.parentElement ? [...canvas.parentElement.classList].sort() : [];
      const state = canvas ? stateFor(canvas) : null;
      let pixels = null;
      let pixelError = null;
      if (canvas && pixelSet.has(index)) {
        try { pixels = pixelHash(canvas); } catch (error) { pixelError = String(error?.name || 'readback_failed'); }
      }
      return {
        index,
        wrapperNode: nodeId(wrapper),
        classes,
        wrapperRect: [rect.x, rect.y, rect.width, rect.height],
        wrapperCenterInViewport: centerInViewport,
        canvasCount: canvases.length,
        canvas: canvas ? {
          node: nodeId(canvas),
          width: canvas.width,
          height: canvas.height,
          rect: [canvasRect.x, canvasRect.y, canvasRect.width, canvasRect.height],
          parentNode: nodeId(canvas.parentElement),
          parentClasses,
          ready: classes.includes('mode-loaded') && classes.includes('mode-rendered') &&
            parentClasses.includes('-cv-page-canvas') && canvas.width > 0 && canvas.height > 0,
          visible: canvasVisible,
          generation: state.generation,
          writes: state.writes,
          pixels,
          pixelError,
        } : null,
      };
    }) : [];
    return {
      url: location.href,
      title: document.title,
      readyState: document.readyState,
      viewerCount: document.querySelectorAll('#comici-viewer').length,
      pagesCount: document.querySelectorAll('#xCVPages').length,
      seekCount: document.querySelectorAll('#xCVSeekBar').length,
      viewerNode: nodeId(viewer),
      pagesNode: nodeId(pages),
      seekNode: nodeId(seek),
      viewerClasses: viewer ? [...viewer.classList].sort() : [],
      viewerNavOpen: viewer ? viewer.classList.contains('mode-nav-open') : null,
      viewerSplashCount: viewer ? viewer.querySelectorAll('.-cv-splash').length : null,
      seek: seek ? {
        type: seek.type,
        value: seek.value,
        min: seek.min,
        max: seek.max,
        step: seek.step,
        disabled: seek.disabled,
      } : null,
      pages: pages ? {className: pages.className, childCount: pages.children.length} : null,
      viewport,
      domGeneration,
      captureDomGeneration,
      slots,
      terminalMarkerCount: document.querySelectorAll('#xCVLastPage').length,
      terminalMarkerParentIndex: (() => {
        const marker = one('#xCVLastPage');
        const wrapper = marker?.closest('.-cv-page');
        return wrapper?.parentElement === pages ? [...pages.children].indexOf(wrapper) : null;
      })(),
    };
  };
  const integrity = () => {
    if (HTMLCanvasElement.prototype.getContext !== nativeGetContext ||
        HTMLCanvasElement.prototype.toDataURL !== nativeToDataURL ||
        contextPrototype.getImageData !== nativeGetImageData ||
        contextPrototype.getContextAttributes !== nativeGetContextAttributes ||
        contextPrototype.getTransform !== nativeGetTransform ||
        contextPrototype.setTransform !== nativeSetTransform) return false;
    for (const [name, original] of originals) {
      if (contextPrototype[name] !== wrapped.get(name) || typeof original !== 'function') return false;
    }
    for (const [name, descriptor] of dimensionDescriptors) {
      if (Object.getOwnPropertyDescriptor(HTMLCanvasElement.prototype, name)?.set !== descriptor.set) return false;
    }
    if (!integrityChecks.every(check => {
      try { return check(); } catch (_) { return false; }
    })) return false;
    return true;
  };
  window.__younganimalViewerCapture = {
    inspect, integrity, stateFor,
    mutationsSince(generation) {
      if (!Number.isSafeInteger(generation) || generation < 0) {
        return {available: false, complete: false, fromGeneration: null,
          coverageContiguous: false, toGeneration: domGeneration, droppedCount: droppedMutationCount,
          unrecordedCount: unrecordedMutationCount, records: []};
      }
      const firstGeneration = mutationJournal[0]?.generation ?? domGeneration + 1;
      const coverageContiguous = !mutationCoverageLost && generation <= domGeneration &&
        generation >= firstGeneration - 1;
      return {available: true,
        complete: coverageContiguous, coverageContiguous,
        fromGeneration: generation, toGeneration: domGeneration,
        droppedCount: droppedMutationCount, unrecordedCount: unrecordedMutationCount,
        records: mutationJournal.filter(record => record.generation > generation).slice(0, MAX_MUTATION_JOURNAL)};
    },
    registerDrawObserver(callback) {
      if (typeof callback !== 'function') throw new TypeError('draw observer must be callable');
      drawObservers.add(callback);
      return () => drawObservers.delete(callback);
    },
    raw: {
      drawImage: nativeDrawImage, getContext: nativeGetContext,
      getImageData: nativeGetImageData, toDataURL: nativeToDataURL,
      getContextAttributes: nativeGetContextAttributes, getTransform: nativeGetTransform,
      setTransform: nativeSetTransform,
    },
  };
})()"""

SNAPSHOT_SCRIPT = r"""({pixelSlots = []} = {}) => {
  const api = window.__younganimalViewerCapture;
  if (!api || typeof api.inspect !== 'function' || !api.integrity())
    return {observerReady: false};
  return {observerReady: true, snapshot: api.inspect(pixelSlots)};
}"""

COLLECT_CAPTURE_SCRIPT = r"""({expectedSlots, expectedSeek, episodePath, maxPngChars}) => {
  const api = window.__younganimalViewerCapture;
  if (!api || typeof api.inspect !== 'function' || !api.integrity())
    return {ok: false, reason: 'observer_integrity_lost'};
  const before = api.inspect(expectedSlots);
  const fail = reason => ({ok: false, reason});
  if (location.pathname !== episodePath || location.search || location.hash || before.url !== location.href)
    return fail('episode_route_changed');
  if (before.viewerCount !== 1 || before.pagesCount !== 1 || before.seekCount !== 1 ||
      before.seek?.value !== String(expectedSeek)) return fail('viewer_identity_changed');
  const beforePages = document.querySelector('#xCVPages');
  const beforeViewer = document.querySelector('#comici-viewer');
  const beforeSeek = document.querySelector('#xCVSeekBar');
  const slots = [];
  for (const index of expectedSlots) {
    const wrapper = beforePages?.children[index];
    const canvasNodes = wrapper ? [...wrapper.querySelectorAll('canvas')] : [];
    const row = before.slots[index];
    const canvas = canvasNodes.length === 1 ? canvasNodes[0] : null;
    if (!wrapper || !canvas || row?.canvas?.node == null || !row.canvas.ready || !row.canvas.visible ||
        !row.wrapperCenterInViewport || row.canvas.pixelError || row.canvas.pixels == null)
      return fail('body_canvas_not_ready');
    slots.push({index, wrapper, canvas, row, data: null});
  }
  try {
    for (const slot of slots) {
      slot.data = slot.canvas.toDataURL('image/png');
      if (typeof slot.data !== 'string' || !slot.data.startsWith('data:image/png;base64,') ||
          slot.data.length > maxPngChars) return fail('png_readback_invalid');
    }
  } catch (_) { return fail('png_readback_failed'); }
  const after = api.inspect(expectedSlots);
  if (location.pathname !== episodePath || location.search || location.hash ||
      beforeViewer !== document.querySelector('#comici-viewer') ||
      beforePages !== document.querySelector('#xCVPages') || beforeSeek !== document.querySelector('#xCVSeekBar') ||
      before.captureDomGeneration !== after.captureDomGeneration || before.url !== after.url ||
      before.viewerClasses.join('|') !== after.viewerClasses.join('|') ||
      before.seek.value !== after.seek.value || before.seek.min !== after.seek.min ||
      before.seek.max !== after.seek.max || before.seek.step !== after.seek.step ||
      before.pages.childCount !== after.pages.childCount ||
      before.viewport.width !== after.viewport.width || before.viewport.height !== after.viewport.height ||
      before.viewport.dpr !== after.viewport.dpr) return fail('viewer_state_changed_during_capture');
  const images = [];
  for (const slot of slots) {
    const row = after.slots[slot.index];
    const canvasNodes = [...(beforePages.children[slot.index]?.querySelectorAll('canvas') || [])];
    if (beforePages.children[slot.index] !== slot.wrapper || canvasNodes.length !== 1 ||
        canvasNodes[0] !== slot.canvas || row?.wrapperNode !== slot.row.wrapperNode ||
        row?.canvas?.node !== slot.row.canvas.node || row.canvas.parentNode !== slot.row.canvas.parentNode ||
        row.canvas.width !== slot.row.canvas.width || row.canvas.height !== slot.row.canvas.height ||
        row.canvas.generation !== slot.row.canvas.generation || row.canvas.writes !== slot.row.canvas.writes ||
        row.canvas.pixels !== slot.row.canvas.pixels || row.classes.join('|') !== slot.row.classes.join('|') ||
        row.canvas.pixelError || !row.canvas.ready || !row.canvas.visible || !row.wrapperCenterInViewport)
      return fail('canvas_identity_or_pixels_changed_during_capture');
    images.push({slot: slot.index, width: row.canvas.width, height: row.canvas.height,
      pixel_fingerprint: row.canvas.pixels, png: slot.data});
  }
  return {ok: true, before, after, images};
}"""


@dataclass(frozen=True, slots=True)
class ViewerObservation:
    seek_value: int
    seek_min: int
    seek_max: int
    seek_step: int
    body_slots: tuple[int, ...]
    ci_slot: int
    layout_variant: str
    initial_blank: bool
    page_state: str
    active_slots: tuple[int, ...]
    ready_slots: tuple[int, ...]
    raw: dict[str, object]


def _classes(value: object, label: str) -> frozenset[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise UnknownPageStateError(f"Younganimal {label} classes are malformed")
    return frozenset(value)


def _parse_viewer_observation(raw: object, *, expected_url: str) -> ViewerObservation:
    if not isinstance(raw, dict) or raw.get("observerReady") is False:
        raise UnknownPageStateError("Younganimal viewer observer is unavailable or malformed")
    capture_dom_generation = raw.get("captureDomGeneration")
    if type(capture_dom_generation) is not int or capture_dom_generation < 0:
        raise UnknownPageStateError("Younganimal capture mutation epoch is missing or malformed")
    if raw.get("url") != expected_url or raw.get("viewerCount") != 1 or raw.get("pagesCount") != 1 or raw.get("seekCount") != 1:
        raise UnknownPageStateError("Younganimal viewer route or root selectors changed")
    viewer_classes = _classes(raw.get("viewerClasses"), "viewer")
    if not {"mode-spread", "mode-dir-rtl", "mode-nav-dir-rtl"}.issubset(viewer_classes):
        raise UnknownPageStateError("Younganimal reader direction or spread mode is unknown")
    layout_variant = "top_emptypage" if "mode-has-top-emptypage" in viewer_classes else "standard"
    seek = raw.get("seek")
    if not isinstance(seek, dict) or seek.get("type") != "range" or seek.get("disabled") is not False:
        raise UnknownPageStateError("Younganimal public seek control is missing or disabled")
    try:
        seek_value, seek_min, seek_max, seek_step = (
            int(seek[name]) for name in ("value", "min", "max", "step")
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise UnknownPageStateError("Younganimal public seek values are malformed") from exc
    slots = raw.get("slots")
    pages = raw.get("pages")
    if (
        not isinstance(slots, list)
        or len(slots) < 9
        or not isinstance(pages, dict)
        or pages.get("childCount") != len(slots)
    ):
        raise UnknownPageStateError("Younganimal physical page wrappers are incomplete")
    expected_seek_max = len(slots) if layout_variant == "top_emptypage" else len(slots) - 1
    if seek_min != 1 or seek_step != 2 or seek_max != expected_seek_max or seek_max % 2 != 1:
        raise UnknownPageStateError("Younganimal seek range does not match its physical wrapper layout")
    if not 1 <= seek_value <= seek_max or (seek_max - seek_value) % seek_step:
        raise UnknownPageStateError("Younganimal selected seek value is outside its observed range")

    parsed_slots: list[dict[str, object]] = []
    for index, slot in enumerate(slots):
        if not isinstance(slot, dict) or slot.get("index") != index:
            raise UnknownPageStateError("Younganimal physical page order changed")
        classes = _classes(slot.get("classes"), f"slot {index}")
        if "-cv-page" not in classes:
            raise UnknownPageStateError("Younganimal physical wrapper class is missing")
        canvas_count = slot.get("canvasCount")
        canvas = slot.get("canvas")
        if not isinstance(canvas_count, int) or canvas_count < 0 or (canvas_count == 1) != isinstance(canvas, dict):
            raise UnknownPageStateError("Younganimal physical canvas count is ambiguous")
        parsed_slots.append(slot)

    lead_classes = _classes(parsed_slots[0].get("classes"), "lead-in")
    if lead_classes != frozenset({"-cv-page", "mode-empty", "mode-pr", "mode-top-pr"}) or parsed_slots[0].get("canvasCount") != 0:
        raise UnknownPageStateError("Younganimal leading PR placeholder changed")
    body_start = 1
    if layout_variant == "top_emptypage":
        blank = parsed_slots[1]
        if (
            _classes(blank.get("classes"), "top empty page")
            != frozenset({"-cv-page", "mode-empty"})
            or blank.get("canvasCount") != 0
        ):
            raise UnknownPageStateError("Younganimal top-empty-page wrapper changed")
        body_start = 2
    tail_sets = (
        frozenset({"-cv-page", "mode-ci"}),
        frozenset({"-cv-page", "mode-empty", "mode-pr"}),
        frozenset({"-cv-page", "mode-empty", "mode-pr"}),
        frozenset({"-cv-page", "mode-good"}),
        frozenset({"-cv-page", "mode-last"}),
    )
    ci_slot = len(parsed_slots) - len(tail_sets)
    for index, expected_classes in enumerate(tail_sets, start=ci_slot):
        slot = parsed_slots[index]
        if _classes(slot.get("classes"), f"tail slot {index}") != expected_classes or slot.get("canvasCount") != 0:
            raise UnknownPageStateError("Younganimal CI/PR/Good/Last tail roles changed")
    if ci_slot <= body_start:
        raise UnknownPageStateError("Younganimal viewer has no contiguous body region")
    body_slots = tuple(range(body_start, ci_slot))
    allowed_body_classes = {
        frozenset({"-cv-page"}),
        frozenset({"-cv-page", "mode-loading"}),
        frozenset({"-cv-page", "mode-loading", "mode-req-render"}),
        frozenset({"-cv-page", "mode-loaded"}),
        frozenset({"-cv-page", "mode-loaded", "mode-rendered"}),
    }
    for index in body_slots:
        slot = parsed_slots[index]
        classes = _classes(slot.get("classes"), f"body slot {index}")
        if classes not in allowed_body_classes:
            raise UnknownPageStateError("Younganimal body slot has an unobserved state class")
        canvas = slot.get("canvas")
        if isinstance(canvas, dict):
            width, height = canvas.get("width"), canvas.get("height")
            if not isinstance(width, int) or not isinstance(height, int) or width <= 0 or height <= 0:
                raise UnknownPageStateError("Younganimal body canvas dimensions are invalid")
    marker_count = raw.get("terminalMarkerCount")
    marker_index = raw.get("terminalMarkerParentIndex")
    focus = seek_max - seek_value + 1
    initial_blank = layout_variant == "top_emptypage" and seek_value == seek_max
    active_slots = tuple(index for index in (focus - 1, focus) if index in body_slots)
    if seek_value == seek_min:
        if (
            "mode-last-page" not in viewer_classes
            or marker_count != 1
            or marker_index != len(parsed_slots) - 1
            or parsed_slots[-1].get("wrapperCenterInViewport") is not True
            or any(parsed_slots[index].get("wrapperCenterInViewport") is True for index in body_slots)
        ):
            raise UnknownPageStateError("Younganimal terminal state lacks its unique Last marker")
        state = "end"
        active_slots = (ci_slot + 2, ci_slot + 3, ci_slot + 4)
    elif "mode-last-page" in viewer_classes:
        raise UnknownPageStateError("Younganimal Last marker appeared before the minimum seek value")
    elif initial_blank:
        if (
            {"mode-first-page", "mode-top-pr-page"}.difference(viewer_classes)
            or parsed_slots[1].get("wrapperCenterInViewport") is not True
        ):
            raise UnknownPageStateError("Younganimal top empty page lacks its observed initial state")
        state = "initial_blank"
        active_slots = (1,)
    elif seek_value == seek_max and layout_variant == "standard":
        if {"mode-first-page", "mode-top-pr-page"}.difference(viewer_classes):
            raise UnknownPageStateError("Younganimal first/top-PR marker is missing at maximum seek")
        active_slots = (body_slots[0],)
        state = "content"
    elif active_slots:
        if "mode-first-page" in viewer_classes or "mode-top-pr-page" in viewer_classes:
            raise UnknownPageStateError("Younganimal first-page markers persisted after rewind")
        if layout_variant == "standard":
            if focus == ci_slot and not {"mode-pr-page", "mode-ci-page"}.issubset(viewer_classes):
                raise UnknownPageStateError("Younganimal final body/CI spread markers are incomplete")
            if focus != ci_slot and ("mode-pr-page" in viewer_classes or "mode-ci-page" in viewer_classes):
                raise UnknownPageStateError("Younganimal CI/PR marker appeared at another body seek")
        elif "mode-pr-page" in viewer_classes or "mode-ci-page" in viewer_classes:
            raise UnknownPageStateError("Younganimal top-empty body spread has unexpected CI/PR markers")
        state = "content"
    elif layout_variant == "standard" and focus == ci_slot + 2:
        if (
            "mode-pr-page" not in viewer_classes
            or "mode-ci-page" in viewer_classes
            or any(parsed_slots[index].get("wrapperCenterInViewport") is True for index in body_slots)
            or any(parsed_slots[index].get("wrapperCenterInViewport") is not True for index in (ci_slot + 1, ci_slot + 2))
        ):
            raise UnknownPageStateError("Younganimal observed CI/PR interstitial markers changed")
        state = "ad"
        active_slots = (ci_slot, ci_slot + 1, ci_slot + 2)
    else:
        raise UnknownPageStateError("Younganimal seek value maps to no observed body or terminal state")

    active_ready: list[int] = []
    if state == "content":
        for index in active_slots:
            slot = parsed_slots[index]
            canvas = slot.get("canvas")
            if (
                isinstance(canvas, dict)
                and canvas.get("ready") is True
                and canvas.get("visible") is True
                and slot.get("wrapperCenterInViewport") is True
            ):
                active_ready.append(index)
    if state == "end" and any(parsed_slots[index].get("canvasCount") for index in body_slots):
        # Historical canvases may remain elsewhere in the DOM; terminal is
        # based on no body page being the selected spread, not global cleanup.
        pass
    return ViewerObservation(
        seek_value=seek_value,
        seek_min=seek_min,
        seek_max=seek_max,
        seek_step=seek_step,
        body_slots=body_slots,
        ci_slot=ci_slot,
        layout_variant=layout_variant,
        initial_blank=initial_blank,
        page_state=state,
        active_slots=tuple(active_slots),
        ready_slots=tuple(active_ready),
        raw=raw,
    )


def decode_canvas_png(value: object, *, width: int, height: int) -> tuple[bytes, str, str]:
    prefix = "data:image/png;base64,"
    if not isinstance(value, str) or not value.startswith(prefix) or len(value) > 4 * ((MAX_PNG_BYTES + 2) // 3) + len(prefix):
        raise UnknownPageStateError("Younganimal rendered PNG readback is malformed or oversized")
    try:
        data = base64.b64decode(value.partition(",")[2], validate=True)
    except (binascii.Error, ValueError) as exc:
        raise UnknownPageStateError("Younganimal rendered PNG base64 is malformed") from exc
    if len(data) > MAX_PNG_BYTES:
        raise UnknownPageStateError("Younganimal rendered PNG exceeds its byte bound")
    try:
        with Image.open(io.BytesIO(data)) as image:
            if image.format != "PNG" or image.size != (width, height) or getattr(image, "n_frames", 1) != 1:
                raise UnknownPageStateError("Younganimal rendered PNG dimensions or format changed")
            image.verify()
        with Image.open(io.BytesIO(data)) as image:
            image.load()
            rgba = image.convert("RGBA").tobytes()
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        if isinstance(exc, UnknownPageStateError):
            raise
        raise UnknownPageStateError("Younganimal rendered PNG did not decode cleanly") from exc
    first = 2166136261
    second = 0x9E3779B9
    for index, byte in enumerate(rgba):
        first = ((first ^ byte) * 16777619) & 0xFFFFFFFF
        second = ((second + byte + (index & 255)) * 2246822519) & 0xFFFFFFFF
    return data, hashlib.sha256(rgba).hexdigest(), f"{first:08x}:{second:08x}"


def decode_capture_results(value: object, *, expected_slots: tuple[int, ...]) -> tuple[CaptureResult, ...]:
    if not isinstance(value, dict) or value.get("ok") is not True:
        reason = value.get("reason") if isinstance(value, dict) else "malformed_result"
        raise UnknownPageStateError(f"Younganimal atomic canvas readback failed ({reason})")
    images = value.get("images")
    if not isinstance(images, list) or len(images) != len(expected_slots):
        raise UnknownPageStateError("Younganimal rendered PNG spread is incomplete")
    captures: list[CaptureResult] = []
    for expected, image in zip(expected_slots, images, strict=True):
        if not isinstance(image, dict) or image.get("slot") != expected:
            raise UnknownPageStateError("Younganimal rendered PNG slot order changed")
        width, height = image.get("width"), image.get("height")
        if not isinstance(width, int) or not isinstance(height, int) or width <= 0 or height <= 0:
            raise UnknownPageStateError("Younganimal rendered PNG dimensions are invalid")
        data, _pixel_sha256, pixel_fingerprint = decode_canvas_png(
            image.get("png"), width=width, height=height
        )
        if image.get("pixel_fingerprint") != pixel_fingerprint:
            raise UnknownPageStateError("Younganimal PNG pixels disagree with the atomic canvas proof")
        captures.append(CaptureResult(data, width, height, "image/png", ".png"))
    return tuple(captures)


__all__ = [
    "COLLECT_CAPTURE_SCRIPT",
    "MAX_PNG_BYTES",
    "OBSERVER_INIT_SCRIPT",
    "SNAPSHOT_SCRIPT",
    "ViewerObservation",
    "_parse_viewer_observation",
    "decode_capture_results",
]
