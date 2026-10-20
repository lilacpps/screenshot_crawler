"""Verified Younganimal draw-time canvas snapshots with rendered-PNG fallback."""

from __future__ import annotations

import base64
import binascii
import io
from dataclasses import dataclass

from PIL import Image, UnidentifiedImageError, features

from screenshot_crawler.core.capture import CaptureResult
from screenshot_crawler.core.errors import UnknownPageStateError

MAX_IMAGE_BYTES = 8_000_000
MAX_CANVAS_PIXELS = 16_000_000
MAX_SPREAD_PIXELS = 32_000_000
MAX_CANDIDATES = 2


OBSERVER_INIT_SCRIPT = r"""(() => {
  if (window.__younganimalNativeCapture) return;
  const capture = window.__younganimalViewerCapture;
  if (!capture || typeof capture.registerDrawObserver !== 'function' || !capture.raw) return;
  try {
  const raw = capture.raw;
  const MAX_CANVAS_PIXELS = 16000000;
  const MAX_SPREAD_PIXELS = 32000000;
  const MAX_CANDIDATES = 2;
  const candidates = new Map();
  const pending = new WeakMap();
  const clipUnsafe = new WeakSet();
  const proofs = new Map();
  let candidateSpread = null;
  let nextProof = 1;
  const apiIdentity = capture;

  const sameArray = (left, right) => left.length === right.length &&
    left.every((value, index) => value === right[index]);
  const oddBodyPageMarkersMatch = (viewer, value, max, noTopPr = false) => {
    let expected;
    if (value === max) expected = noTopPr ? ['mode-first-page'] : ['mode-first-page', 'mode-top-pr-page'];
    else if (value === 5) expected = ['mode-ci-page', 'mode-pr-page'];
    else if (value === 3) expected = ['mode-pr-page'];
    else if (value === 1) expected = ['mode-last-page'];
    else if (value >= 7 && value < max && value % 2 === 1) expected = [];
    else return false;
    const names = [
      'mode-first-page', 'mode-top-pr-page', 'mode-pr-page', 'mode-ci-page', 'mode-last-page',
    ].filter(name => viewer.classList.contains(name));
    return names.length === expected.length && expected.every(name => names.includes(name));
  };
  const classes = node => node ? [...node.classList].sort() : [];
  const exactClasses = (node, expected) => sameArray(classes(node), expected.slice().sort());
  const wrapperCenterInViewport = node => {
    const rect = node?.getBoundingClientRect();
    if (!rect || rect.width <= 0 || rect.height <= 0) return false;
    const x = rect.x + rect.width / 2, y = rect.y + rect.height / 2;
    return x >= 0 && x <= innerWidth && y >= 0 && y <= innerHeight;
  };
  const visibleCenterInViewport = node => {
    if (!node || !wrapperCenterInViewport(node)) return false;
    for (let current = node; current && current instanceof Element; current = current.parentElement) {
      const style = getComputedStyle(current);
      if (style.display === 'none' || style.visibility === 'hidden' || style.visibility === 'collapse' ||
          Number(style.opacity) <= 0) return false;
    }
    if (typeof node.checkVisibility === 'function') {
      try { return node.checkVisibility({checkOpacity: true, checkVisibilityCSS: true}); }
      catch (_) { return false; }
    }
    return true;
  };
  const oddBodyCandidate = (viewer, children, seek, noTopPr = false) => {
    const bodyCount = children.length - 6;
    return viewer instanceof Element && viewer.classList.contains('mode-has-top-emptypage') === noTopPr &&
      (!noTopPr || (viewer.classList.contains('mode-h') &&
        !['mode-v', 'mode-single'].some(name => viewer.classList.contains(name)))) &&
      viewer.classList.contains('mode-has-comic-info') &&
      bodyCount >= 3 && bodyCount % 2 === 1 && seek?.type === 'range' && !seek.disabled &&
      Number(seek.min) === 1 && Number(seek.max) === children.length && Number(seek.step) === 2;
  };
  const exactStandardOddBody = (viewer, pages, children, seek, noTopPr = false, forDraw = false) => {
    const ciIndex = children.length - 5;
    const bodyCount = children.length - 6;
    if (!(viewer instanceof Element) || !(pages instanceof Element) ||
        !oddBodyCandidate(viewer, children, seek, noTopPr) || bodyCount < 3 || bodyCount % 2 !== 1 ||
        !['mode-spread', 'mode-dir-rtl', 'mode-nav-dir-rtl'].every(name => viewer.classList.contains(name)) ||
        !['mode-has-pr', 'mode-has-comic-info', 'mode-has-good-page'].every(name => viewer.classList.contains(name)) ||
        !exactClasses(children[0], noTopPr ? ['-cv-page', 'mode-empty'] : ['-cv-page', 'mode-empty', 'mode-pr', 'mode-top-pr']) ||
        children[0].querySelectorAll('canvas').length !== 0 ||
        !exactClasses(children[ciIndex], ['-cv-page', 'mode-ci']) ||
        children[ciIndex].querySelectorAll('canvas').length !== 0) return false;
    const allowedBody = [
      ['-cv-page'], ['-cv-page', 'mode-loading'],
      ['-cv-page', 'mode-loading', 'mode-req-render'],
      ['-cv-page', 'mode-loaded'], ['-cv-page', 'mode-loaded', 'mode-rendered'],
    ];
    for (let slot = 1; slot <= bodyCount; slot += 1) {
      if (!children[slot] || children[slot].parentElement !== pages ||
          !allowedBody.some(expected => exactClasses(children[slot], expected))) return false;
    }
    const tail = [
      ['-cv-page', 'mode-empty', 'mode-pr'], ['-cv-page', 'mode-empty', 'mode-pr'],
      ['-cv-page', 'mode-good'], ['-cv-page', 'mode-last'],
    ];
    for (let offset = 0; offset < tail.length; offset += 1) {
      const wrapper = children[ciIndex + 1 + offset];
      if (!wrapper || !exactClasses(wrapper, tail[offset]) || wrapper.querySelectorAll('canvas').length !== 0)
        return false;
    }
    const value = Number(seek.value);
    if (!oddBodyPageMarkersMatch(viewer, value, children.length, noTopPr)) return false;
    const focus = children.length - value + 1;
    if (noTopPr) {
      // Incoming bodies may draw before the seek translation settles. Selection
      // and postproof require all final centers; draw replay still binds the nodes.
      if (!forDraw && !sameArray(children.flatMap((node, i) => wrapperCenterInViewport(node) ? [i] : []),
          [focus - 1, focus].filter(i => i >= 0 && i < children.length))) return false;
      if (value === 1) {
        const markers = [...document.querySelectorAll('#xCVLastPage')];
        if (markers.length !== 1 || markers[0].closest('.-cv-page') !== children.at(-1) ||
            !visibleCenterInViewport(markers[0])) return false;
      }
      return true;
    }
    const expectedBodyCenters = value === children.length ? [1]
      : value >= 7 ? [focus - 1, focus].filter(slot => slot >= 1 && slot <= bodyCount)
      : [];
    const actualBodyCenters = [];
    for (let slot = 1; slot <= bodyCount; slot += 1) {
      if (wrapperCenterInViewport(children[slot])) actualBodyCenters.push(slot);
    }
    if (!sameArray(actualBodyCenters, expectedBodyCenters)) return false;
    if (value === children.length && !wrapperCenterInViewport(children[0])) return false;
    if (value === 5 && (!wrapperCenterInViewport(children[ciIndex]) ||
        !wrapperCenterInViewport(children[ciIndex + 1]))) return false;
    if (value === 3 && (!wrapperCenterInViewport(children[ciIndex + 2]) ||
        !wrapperCenterInViewport(children[ciIndex + 3]))) return false;
    if (value === 1) {
      const markers = [...document.querySelectorAll('#xCVLastPage')];
      const lastWrapper = markers.length === 1 ? markers[0].closest('.-cv-page') : null;
      if (!lastWrapper || lastWrapper !== children.at(-1) || lastWrapper.parentElement !== pages ||
          !wrapperCenterInViewport(children.at(-1))) return false;
    }
    return true;
  };
  const noCiPageMarkersMatch = (viewer, value, max, evenWrappers) => {
    let expected;
    if (value === max) expected = ['mode-first-page'];
    else if (value === 3 || (value === 5 && !evenWrappers)) expected = ['mode-pr-page'];
    else if (value === 1) expected = evenWrappers ? ['mode-pr-page', 'mode-last-page'] : ['mode-last-page'];
    else if (value >= (evenWrappers ? 5 : 7) && value < max && value % 2 === 1) expected = [];
    else return false;
    const names = [
      'mode-first-page', 'mode-top-pr-page', 'mode-pr-page', 'mode-ci-page', 'mode-last-page',
    ].filter(name => viewer.classList.contains(name));
    return sameArray(names, expected);
  };
  const noCiCandidate = (viewer, children, seek) => {
    const topEmpty = viewer?.classList.contains('mode-has-top-emptypage');
    const bodyCount = children.length - (topEmpty ? 5 : 4);
    // Even wrapper totals have max=N-1 and distinct PR/Last phases.
    return viewer instanceof Element && viewer.classList.contains('mode-h') &&
      viewer.classList.contains('mode-spread') && viewer.classList.contains('mode-dir-rtl') &&
      viewer.classList.contains('mode-nav-dir-rtl') &&
      viewer.classList.contains('mode-has-pr') && viewer.classList.contains('mode-has-good-page') &&
      !viewer.classList.contains('mode-has-comic-info') &&
      !viewer.classList.contains('mode-v') && !viewer.classList.contains('mode-single') &&
      bodyCount >= (topEmpty ? 4 : 5) && seek?.type === 'range' && !seek.disabled &&
      Number(seek.min) === 1 && Number(seek.max) === children.length - (children.length % 2 === 0 ? 1 : 0) && Number(seek.step) === 2;
  };
  const exactNoCiLayout = (viewer, pages, children, seek, forDraw = false) => {
    const bodyStart = viewer.classList.contains('mode-has-top-emptypage') ? 1 : 0;
    const tailStart = children.length - 4;
    const evenWrappers = children.length % 2 === 0;
    const max = children.length - (evenWrappers ? 1 : 0);
    if (!(pages instanceof Element) || !noCiCandidate(viewer, children, seek) ||
        (bodyStart === 1 && (!exactClasses(children[0], ['-cv-page', 'mode-empty']) ||
        children[0].querySelectorAll('canvas').length !== 0))) return false;
    const allowedBody = [
      ['-cv-page'], ['-cv-page', 'mode-loading'],
      ['-cv-page', 'mode-loading', 'mode-req-render'],
      ['-cv-page', 'mode-loaded'], ['-cv-page', 'mode-loaded', 'mode-rendered'],
    ];
    for (let slot = bodyStart; slot < tailStart; slot += 1) {
      const wrapper = children[slot];
      if (!wrapper || wrapper.parentElement !== pages ||
          !allowedBody.some(expected => exactClasses(wrapper, expected))) return false;
    }
    const tail = [
      ['-cv-page', 'mode-empty', 'mode-pr'], ['-cv-page', 'mode-empty', 'mode-pr'],
      ['-cv-page', 'mode-good'], ['-cv-page', 'mode-last'],
    ];
    for (let offset = 0; offset < tail.length; offset += 1) {
      const wrapper = children[tailStart + offset];
      if (!wrapper || wrapper.parentElement !== pages || !exactClasses(wrapper, tail[offset]) ||
          wrapper.querySelectorAll('canvas').length !== 0) return false;
    }
    const value = Number(seek.value);
    if (!noCiPageMarkersMatch(viewer, value, max, evenWrappers)) return false;
    const focus = max - value + 1;
    const expectedCenters = [focus - 1, focus].filter(slot => slot >= 0 && slot < children.length);
    const actualCenters = [];
    for (let slot = 0; slot < children.length; slot += 1) {
      if (wrapperCenterInViewport(children[slot])) actualCenters.push(slot);
    }
    // Incoming bodies draw before the public seek's CSS translation settles.
    // Selection/postproof still require final centers; replay and equal-size
    // wrapper/target translation bind the draw-time source to the selected body.
    if (!forDraw && !sameArray(actualCenters, expectedCenters)) return false;
    if (value === max && expectedCenters[0] !== 0) return false;
    if (value === 1) {
      const markers = [...document.querySelectorAll('#xCVLastPage')];
      const lastWrapper = markers.length === 1 ? markers[0].closest('.-cv-page') : null;
      if (!lastWrapper || lastWrapper !== children.at(-1) || lastWrapper.parentElement !== pages ||
          !wrapperCenterInViewport(lastWrapper)) return false;
      if (!visibleCenterInViewport(markers[0])) return false;
    }
    return true;
  };
  const exactShortStandardLayout = (viewer, pages, children, seek, forDraw) => {
    if (![7, 8].includes(children.length) || !viewer.contains(pages) || !viewer.contains(seek) ||
        !['mode-h', 'mode-spread', 'mode-dir-rtl', 'mode-nav-dir-rtl', 'mode-has-pr',
          'mode-has-comic-info', 'mode-has-good-page'].every(name => viewer.classList.contains(name)) ||
        ['mode-has-top-emptypage', 'mode-v', 'mode-single'].some(name => viewer.classList.contains(name)) ||
        seek.type !== 'range' || seek.disabled || Number(seek.min) !== 1 || Number(seek.max) !== 7 ||
        Number(seek.step) !== 2) return false;
    const bodyCount = children.length - 6, ci = bodyCount + 1;
    const roles = [[0, ['-cv-page', 'mode-empty', 'mode-pr', 'mode-top-pr']],
      [ci, ['-cv-page', 'mode-ci']], [ci + 1, ['-cv-page', 'mode-empty', 'mode-pr']],
      [ci + 2, ['-cv-page', 'mode-empty', 'mode-pr']], [ci + 3, ['-cv-page', 'mode-good']], [ci + 4, ['-cv-page', 'mode-last']]];
    if (roles.some(([i, names]) => children[i]?.parentElement !== pages || !exactClasses(children[i], names) ||
        children[i].querySelectorAll('canvas').length !== 0)) return false;
    const allowed = ['-cv-page', '-cv-page mode-loading', '-cv-page mode-loading mode-req-render',
      '-cv-page mode-loaded', '-cv-page mode-loaded mode-rendered'];
    for (let slot = 1; slot <= bodyCount; slot += 1)
      if (children[slot]?.parentElement !== pages || !allowed.includes(classes(children[slot]).join(' '))) return false;
    const value = Number(seek.value);
    const expected = value === 7 ? ['mode-first-page', 'mode-top-pr-page']
      : value === 5 ? ['mode-ci-page', 'mode-pr-page'] : value === 3 ? ['mode-pr-page']
      : value === 1 ? (bodyCount === 1 ? ['mode-last-page'] : ['mode-last-page', 'mode-pr-page']) : null;
    const flags = ['mode-first-page', 'mode-top-pr-page', 'mode-ci-page', 'mode-pr-page', 'mode-last-page']
      .filter(name => viewer.classList.contains(name));
    if (!expected || flags.length !== expected.length || !expected.every(name => flags.includes(name))) return false;
    // Selection/postproof require final centers; existing replay/translation proof
    // binds incoming draws even when CSS positioning has not settled yet.
    if (forDraw) return true;
    const focus = 8 - value;
    return sameArray(children.flatMap((node, i) => wrapperCenterInViewport(node) ? [i] : []),
      [focus - 1, focus].filter(i => i < children.length));
  };
  const exactPrTailLayout = (viewer, pages, children, seek, prCount, forDraw) => {
    // Prove the observed PR-tail families, including blank and body-parity variants.
    const topEmpty = viewer.classList.contains('mode-has-top-emptypage');
    const bodyStart = topEmpty ? 2 : 1, ci = children.length - prCount - 3;
    const bodyCount = ci - bodyStart;
    const oddBody = !topEmpty && bodyCount % 2 === 1;
    const value = Number(seek.value), max = children.length - (oddBody ? 1 : 0);
    const ciSeek = prCount + (oddBody ? 2 : 4);
    if (![1, 3].includes(prCount) ||
        (topEmpty ? prCount !== 3 || bodyCount < 3 || bodyCount % 2 !== 1
          : oddBody ? prCount !== 3 || bodyCount < 3 : bodyCount < 4) ||
        !viewer.contains(pages) || !viewer.contains(seek) ||
        !['mode-h', 'mode-spread', 'mode-dir-rtl', 'mode-nav-dir-rtl', 'mode-has-pr',
          'mode-has-comic-info', 'mode-has-good-page'].every(name => viewer.classList.contains(name)) ||
        ['mode-v', 'mode-single'].some(name => viewer.classList.contains(name)) ||
        seek.type !== 'range' || seek.disabled || Number(seek.min) !== 1 ||
        Number(seek.max) !== max || Number(seek.step) !== 2 ||
        !Number.isInteger(value) || value < 1 || value > max || (max - value) % 2 !== 0) return false;
    const phase = value === max ? ['mode-first-page', 'mode-top-pr-page']
      : value === ciSeek ? ['mode-ci-page', 'mode-pr-page']
      : value === 1 ? (oddBody ? ['mode-last-page', 'mode-pr-page'] : ['mode-last-page'])
        : value < ciSeek ? ['mode-pr-page'] : [];
    const flags = ['mode-first-page', 'mode-top-pr-page', 'mode-ci-page', 'mode-pr-page', 'mode-last-page']
      .filter(name => viewer.classList.contains(name));
    if (flags.length !== phase.length || !phase.every(name => flags.includes(name))) return false;
    const roles = [[0, ['-cv-page', 'mode-empty', 'mode-pr', 'mode-top-pr']],
      ...(topEmpty ? [[1, ['-cv-page', 'mode-empty']]] : []),
      [ci, ['-cv-page', 'mode-ci']],
      ...Array.from({length: prCount}, (_, i) => [ci + 1 + i, ['-cv-page', 'mode-empty', 'mode-pr']]),
      [ci + prCount + 1, ['-cv-page', 'mode-good']], [ci + prCount + 2, ['-cv-page', 'mode-last']]];
    if (roles.some(([i, names]) => children[i]?.parentElement !== pages || !exactClasses(children[i], names) ||
        children[i].querySelectorAll('canvas').length !== 0)) return false;
    const allowed = ['-cv-page', '-cv-page mode-loading', '-cv-page mode-loading mode-req-render',
      '-cv-page mode-loaded', '-cv-page mode-loaded mode-rendered'];
    for (let slot = bodyStart; slot < ci; slot += 1)
      if (children[slot]?.parentElement !== pages || !allowed.includes(classes(children[slot]).join(' '))) return false;
    if (forDraw) return true;
    const focus = max - Number(seek.value) + 1;
    return sameArray(children.flatMap((node, i) => wrapperCenterInViewport(node) ? [i] : []),
      [focus - 1, focus].filter(i => i >= 0 && i < children.length));
  };
  const attr = context => {
    try {
      const value = typeof raw.getContextAttributes === 'function'
        ? Reflect.apply(raw.getContextAttributes, context, []) : null;
      return value ? {alpha: value.alpha ?? null, colorSpace: value.colorSpace ?? null,
        colorType: value.colorType ?? null, desynchronized: value.desynchronized ?? null} : null;
    } catch (_) { return null; }
  };
  const attrsEqual = (left, right) => !!left && !!right &&
    left.alpha === right.alpha && left.colorSpace === right.colorSpace &&
    left.colorType === right.colorType && left.desynchronized === right.desynchronized;
  const paint = context => {
    try {
      const transform = typeof raw.getTransform === 'function'
        ? Reflect.apply(raw.getTransform, context, []) : null;
      const identity = !!transform && transform.a === 1 && transform.b === 0 &&
        transform.c === 0 && transform.d === 1 && transform.e === 0 && transform.f === 0;
      const shadowColor = String(context.shadowColor).replace(/\s+/g, '').toLowerCase();
      return {attributes: attr(context), identity, alpha: context.globalAlpha,
        composite: context.globalCompositeOperation, filter: context.filter || 'none',
        smoothing: context.imageSmoothingEnabled, smoothingQuality: context.imageSmoothingQuality,
        shadowBlur: context.shadowBlur, shadowOffsetX: context.shadowOffsetX,
        shadowOffsetY: context.shadowOffsetY, shadowColor,
        neutralShadow: context.shadowBlur === 0 && context.shadowOffsetX === 0 &&
          context.shadowOffsetY === 0 && shadowColor === 'rgba(0,0,0,0)'};
    } catch (_) { return null; }
  };
  const paintSupported = value => value && value.attributes?.colorSpace === 'srgb' &&
    value.attributes?.colorType === 'unorm8' && value.identity && value.alpha === 1 &&
    value.composite === 'source-over' && value.filter === 'none' && value.neutralShadow &&
    typeof value.smoothing === 'boolean' &&
    ['low', 'medium', 'high'].includes(value.smoothingQuality);
  const canvasState = canvas => {
    const state = capture.stateFor(canvas);
    return {generation: state.generation, writes: state.writes};
  };
  const pixels = canvas => {
    const context = Reflect.apply(raw.getContext, canvas, ['2d']);
    if (!context) throw new Error('canvas_context_missing');
    return Reflect.apply(raw.getImageData, context, [0, 0, canvas.width, canvas.height]).data;
  };
  const equalPixels = (left, right) => {
    if (!left || !right || left.length !== right.length) return false;
    for (let index = 0; index < left.length; index += 1) if (left[index] !== right[index]) return false;
    return true;
  };
  const normalizedLayout = (forDraw = false) => {
    const viewer = document.querySelector('#comici-viewer');
    const pages = document.querySelector('#xCVPages');
    const seek = document.querySelector('#xCVSeekBar');
    if (document.querySelectorAll('#comici-viewer').length !== 1 ||
        document.querySelectorAll('#xCVPages').length !== 1 ||
        document.querySelectorAll('#xCVSeekBar').length !== 1 || !viewer || !pages || !seek ||
        seek.type !== 'range' || seek.disabled) return null;
    const children = [...pages.children];
    const shortStandard = exactShortStandardLayout(viewer, pages, children, seek, forDraw);
    const oneBody = shortStandard && children.length === 7;
    const twoBody = shortStandard && children.length === 8;
    const topEmptyNoCi = noCiCandidate(viewer, children, seek);
    const prCount = [1, 3].find(count => exactPrTailLayout(viewer, pages, children, seek, count, forDraw)) || 0;
    const ci = topEmptyNoCi ? null : children.length - (prCount ? prCount + 3 : 5);
    const noTopPr = viewer.classList.contains('mode-has-top-emptypage') &&
      exactClasses(children[0], ['-cv-page', 'mode-empty']);
    const hasTopEmptyPage = viewer.classList.contains('mode-has-top-emptypage') && !noTopPr;
    const bodyStart = topEmptyNoCi ? (viewer.classList.contains('mode-has-top-emptypage') ? 1 : 0) : hasTopEmptyPage ? 2 : 1;
    const bodyEnd = topEmptyNoCi ? children.length - 4 : ci;
    const noCiEvenWrappers = topEmptyNoCi && children.length % 2 === 0;
    if ((children.length < 9 && !shortStandard) || bodyEnd <= bodyStart) return null;
    if (topEmptyNoCi) {
      if (!exactNoCiLayout(viewer, pages, children, seek, forDraw)) return null;
    } else if (prCount) {
      // The explicit PR-tail helper proved the complete lead/body/tail structure.
    } else if (
        !exactClasses(children[0], noTopPr ? ['-cv-page', 'mode-empty'] : ['-cv-page', 'mode-empty', 'mode-pr', 'mode-top-pr']) ||
        (hasTopEmptyPage && !exactClasses(children[1], ['-cv-page', 'mode-empty'])) ||
        !exactClasses(children[ci], ['-cv-page', 'mode-ci']) ||
        !exactClasses(children[ci + 1], ['-cv-page', 'mode-empty', 'mode-pr']) ||
        !exactClasses(children[ci + 2], ['-cv-page', 'mode-empty', 'mode-pr']) ||
        !exactClasses(children[ci + 3], ['-cv-page', 'mode-good']) ||
        !exactClasses(children[ci + 4], ['-cv-page', 'mode-last'])) return null;
    const min = Number(seek.min), max = Number(seek.max), step = Number(seek.step), value = Number(seek.value);
    const standardOddBody = !prCount && !topEmptyNoCi && !hasTopEmptyPage && !noTopPr && oddBodyCandidate(viewer, children, seek);
    const noTopPrOddBody = noTopPr && oddBodyCandidate(viewer, children, seek, true);
    const oddBody = standardOddBody || noTopPrOddBody;
    const shortTopEmpty = hasTopEmptyPage && children.length % 2 === 0 && max === children.length - 1;
    if (shortTopEmpty) {
      if (!['mode-h', 'mode-has-pr', 'mode-has-comic-info', 'mode-has-good-page'].every(name => viewer.classList.contains(name)) ||
          ['mode-v', 'mode-single'].some(name => viewer.classList.contains(name)) ||
          ci - bodyStart < 3 || (ci - bodyStart) % 2 !== 1 ||
          children[1].querySelectorAll('canvas').length !== 0) return null;
      const expected = value === max ? ['mode-first-page', 'mode-top-pr-page']
        : value === 5 ? ['mode-ci-page', 'mode-pr-page'] : value === 3 ? ['mode-pr-page']
        : value === 1 ? ['mode-last-page', 'mode-pr-page'] : [];
      const flags = ['mode-first-page', 'mode-top-pr-page', 'mode-ci-page', 'mode-pr-page', 'mode-last-page']
        .filter(name => viewer.classList.contains(name));
      const focus = max - value + 1;
      const centers = children.flatMap((node, index) => wrapperCenterInViewport(node) ? [index] : []);
      // A seek draws the new pair before its CSS translation reaches the viewport.
      // Selection/postproof still require the exact final centers; existing replay and
      // equal-size wrapper/target translation proof bind the draw-time snapshot.
      if (!sameArray(flags.slice().sort(), expected.slice().sort()) ||
          (!forDraw && !sameArray(centers, [focus - 1, focus].filter(index => index >= 0 && index < children.length)))) return null;
    }
    if (min !== 1 || step !== 2 ||
        max !== (topEmptyNoCi ? children.length - (noCiEvenWrappers ? 1 : 0) : prCount ? children.length - (children.length % 2 === 0 ? 1 : 0) : oneBody || (hasTopEmptyPage && !shortTopEmpty) || oddBody ? children.length : children.length - 1) ||
        (oddBody && !exactStandardOddBody(viewer, pages, children, seek, noTopPrOddBody, forDraw)) ||
        !Number.isInteger(value) || value < min || value > max || (max - value) % step !== 0) return null;
    if (viewer.classList.contains('mode-last-page') && !prCount && !oddBody && !topEmptyNoCi) return null;
    const focus = max - value + 1;
    const active = [focus - 1, focus].filter(slot => slot >= bodyStart && slot < bodyEnd);
    if (!active.length && !(oddBody && (value === min || value === 5 || value === 3)) &&
        !(topEmptyNoCi && (value === min || value === 3))) return null;
    const allowedBodyClasses = [
      ['-cv-page'], ['-cv-page', 'mode-loading'],
      ['-cv-page', 'mode-loading', 'mode-req-render'],
      ['-cv-page', 'mode-loaded'], ['-cv-page', 'mode-loaded', 'mode-rendered'],
    ];
    for (let slot = bodyStart; slot < bodyEnd; slot += 1) {
      const names = classes(children[slot]);
      if (!allowedBodyClasses.some(expected => sameArray(names, expected.slice().sort()))) return null;
    }
    const mutationState = capture.inspect([]);
    if (!mutationState || !Number.isSafeInteger(mutationState.domGeneration) || mutationState.domGeneration < 0 ||
        !Number.isSafeInteger(mutationState.captureDomGeneration) || mutationState.captureDomGeneration < 0) return null;
    const roles = prCount ? Array.from({length: prCount + 3}, (_, i) => ci + i) : topEmptyNoCi
      ? [null, bodyEnd, bodyEnd + 1, bodyEnd + 2, bodyEnd + 3]
      : [ci, ci + 1, ci + 2, ci + 3, ci + 4];
    return {viewer, pages, seek, children, ci, bodyStart, bodyEnd, roles,
      variant: oneBody ? 'standard_one_body' : twoBody ? 'standard_two_body' : prCount === 3 ? (hasTopEmptyPage ? 'top_empty_three_pr' : children.length % 2 === 0 ? 'standard_three_pr_odd_body' : 'standard_three_pr') : prCount === 1 ? 'standard_single_pr' : topEmptyNoCi ? (bodyStart === 0 ? (noCiEvenWrappers ? 'no_lead_no_ci_even_body' : 'no_lead_no_ci') : noCiEvenWrappers ? 'top_empty_no_ci_odd_body' : 'top_empty_no_ci') : noTopPrOddBody ? 'top_empty_no_pr_odd_body' : standardOddBody ? 'standard_odd_body' : noTopPr ? 'top_empty_no_pr' : hasTopEmptyPage ? 'top_emptypage' : 'standard', min, max, step, value, active,
      path: location.pathname, dom: mutationState.domGeneration,
      captureDom: mutationState.captureDomGeneration,
      viewport: {width: innerWidth, height: innerHeight, dpr: devicePixelRatio}};
  };
  const targetLocation = (target, layout) => {
    if (!layout) return null;
    const wrapper = target.closest('.-cv-page');
    const holder = target.parentElement;
    if (!wrapper || !holder || wrapper.parentElement !== layout.pages ||
        !holder.classList.contains('-cv-page-canvas') || holder.querySelectorAll('canvas').length !== 1)
      return null;
    const slot = [...layout.pages.children].indexOf(wrapper);
    if (!layout.active.includes(slot)) return null;
    return {wrapper, holder, slot};
  };
  const safeDimensions = (canvas, {width, height} = canvas) =>
    Number.isSafeInteger(width) && Number.isSafeInteger(height) && width > 0 && height > 0 &&
    width * height <= MAX_CANVAS_PIXELS && canvas.width === width && canvas.height === height;
  const fullFrame = (args, source, target) => args.length === 8 &&
    args.every(Number.isFinite) && args[0] === 0 && args[1] === 0 &&
    args[2] === source.width && args[3] === source.height && args[4] === 0 &&
    args[5] === 0 &&
    // Viewer draw sizes can retain a fraction truncated by canvas bitmap sizing.
    // Accept only subpixel overhang and replay the exact observed rectangle.
    Math.floor(args[6]) === target.width && Math.floor(args[7]) === target.height;
  const sourceOptions = attrs => {
    const result = {};
    for (const name of ['alpha', 'colorSpace', 'colorType', 'desynchronized']) {
      if (attrs[name] !== null && attrs[name] !== undefined) result[name] = attrs[name];
    }
    return result;
  };
  const makeSnapshot = (source, sourceAttrs) => {
    const snapshot = document.createElement('canvas');
    snapshot.width = source.width;
    snapshot.height = source.height;
    const context = Reflect.apply(raw.getContext, snapshot, ['2d', sourceOptions(sourceAttrs)]);
    if (!context) return null;
    Reflect.apply(raw.drawImage, context, [source, 0, 0]);
    return {canvas: snapshot, attributes: attr(context)};
  };
  const spreadKey = layout => `${layout.path}|${layout.variant}|${layout.value}|${layout.active.join(',')}`;

  const onDraw = event => {
    const {phase, method, target} = event;
    if (!(target instanceof HTMLCanvasElement)) return;
    if (method === 'clip') {
      clipUnsafe.add(target);
      candidates.delete(target);
      return;
    }
    if (method !== 'drawImage') {
      if (phase === 'after' || phase === 'failed') candidates.delete(target);
      return;
    }
    if (phase === 'failed') {
      pending.delete(target);
      candidates.delete(target);
      return;
    }
    if (phase === 'after') {
      const prepared = pending.get(target);
      pending.delete(target);
      if (!prepared) return;
      try {
        const state = canvasState(target);
        const sourceState = canvasState(prepared.source);
        if (state.generation !== prepared.targetBefore.generation ||
            state.writes !== prepared.targetBefore.writes + 1 ||
            target.width !== prepared.targetWidth || target.height !== prepared.targetHeight ||
            sourceState.generation !== prepared.sourceState.generation ||
            sourceState.writes !== prepared.sourceState.writes ||
            prepared.snapshot.width !== prepared.sourceWidth ||
            prepared.snapshot.height !== prepared.sourceHeight || prepared.snapshot.isConnected ||
            !attrsEqual(prepared.snapshotAttributes, prepared.sourceAttrs)) return;
        candidates.set(target, {...prepared, targetAfter: state});
        if (candidates.size > MAX_CANDIDATES) {
          candidates.clear();
          candidates.set(target, {...prepared, targetAfter: state});
        }
      } catch (_) { candidates.delete(target); }
      return;
    }
    if (phase !== 'before') return;
    candidates.delete(target);
    pending.delete(target);
    try {
      const currentPages = document.querySelector('#xCVPages');
      const currentWrapper = target.closest('.-cv-page');
      if (!currentPages || !currentWrapper || currentWrapper.parentElement !== currentPages) return;
      const layout = normalizedLayout(true);
      const locationRow = targetLocation(target, layout);
      const source = event.source;
      if (!locationRow || !(source instanceof HTMLCanvasElement) ||
          !safeDimensions(source) || !safeDimensions(target) ||
          !fullFrame(event.drawArgs, source, target) || clipUnsafe.has(target)) return;
      const sourceContext = Reflect.apply(raw.getContext, source, ['2d']);
      if (!sourceContext) return;
      const sourceAttrs = attr(sourceContext);
      const targetPaint = paint(event.context);
      if (!sourceAttrs || sourceAttrs.colorSpace !== 'srgb' || sourceAttrs.colorType !== 'unorm8' ||
          !paintSupported(targetPaint) ||
          ['getContext', 'toDataURL', 'width', 'height'].some(name => Object.hasOwn(target, name)) ||
          ['drawImage', 'getContextAttributes', 'getTransform', 'setTransform'].some(name => Object.hasOwn(event.context, name))) return;
      const key = spreadKey(layout);
      if (candidateSpread !== key) { candidates.clear(); candidateSpread = key; }
      const sourceState = canvasState(source);
      const targetBefore = canvasState(target);
      const targetRect = target.getBoundingClientRect();
      const wrapperRect = locationRow.wrapper.getBoundingClientRect();
      const copied = makeSnapshot(source, sourceAttrs);
      const sourceAfterCopy = canvasState(source);
      if (!copied || sourceAfterCopy.generation !== sourceState.generation ||
          sourceAfterCopy.writes !== sourceState.writes || !attrsEqual(copied.attributes, sourceAttrs)) return;
      pending.set(target, {
        target, wrapper: locationRow.wrapper, holder: locationRow.holder,
        pages: layout.pages, viewer: layout.viewer, seek: layout.seek, slot: locationRow.slot,
        episodePath: layout.path, layoutVariant: layout.variant,
        roles: layout.roles.slice(),
        seekValue: layout.value, activeSlots: layout.active.slice(),
        domGeneration: layout.dom, captureDomGeneration: layout.captureDom,
        viewport: layout.viewport,
        targetBefore, targetWidth: target.width, targetHeight: target.height,
        targetRect: [targetRect.x, targetRect.y, targetRect.width, targetRect.height],
        wrapperRect: [wrapperRect.x, wrapperRect.y, wrapperRect.width, wrapperRect.height],
        targetPaint, source, sourceWidth: source.width, sourceHeight: source.height,
        drawArgs: event.drawArgs.slice(),
        sourceState, sourceAttrs, snapshot: copied.canvas, snapshotAttributes: copied.attributes,
      });
    } catch (_) { pending.delete(target); }
  };
  const unregister = capture.registerDrawObserver(onDraw);

  const replay = candidate => {
    const canvas = document.createElement('canvas');
    canvas.width = candidate.targetWidth;
    canvas.height = candidate.targetHeight;
    const context = Reflect.apply(raw.getContext, canvas, ['2d', sourceOptions(candidate.targetPaint.attributes)]);
    if (!context || typeof raw.setTransform !== 'function') throw new Error('replay_context_unavailable');
    Reflect.apply(raw.setTransform, context, [1, 0, 0, 1, 0, 0]);
    context.globalAlpha = 1;
    context.globalCompositeOperation = 'source-over';
    context.imageSmoothingEnabled = candidate.targetPaint.smoothing;
    context.imageSmoothingQuality = candidate.targetPaint.smoothingQuality;
    context.filter = 'none';
    context.shadowBlur = 0;
    context.shadowOffsetX = 0;
    context.shadowOffsetY = 0;
    context.shadowColor = 'rgba(0, 0, 0, 0)';
    Reflect.apply(raw.drawImage, context, [candidate.snapshot, ...candidate.drawArgs]);
    return pixels(canvas);
  };
  const rectEqual = (left, right) => Array.isArray(left) && Array.isArray(right) &&
    left.length === right.length && left.every((value, index) => Math.abs(value - right[index]) < 0.01);
  const rectPureTranslation = (drawTarget, drawWrapper, currentTarget, currentWrapper) => {
    if (![drawTarget, drawWrapper, currentTarget, currentWrapper].every(value =>
      Array.isArray(value) && value.length === 4 && value.every(Number.isFinite))) return false;
    if (Math.abs(drawTarget[2] - currentTarget[2]) >= 0.01 ||
        Math.abs(drawTarget[3] - currentTarget[3]) >= 0.01 ||
        Math.abs(drawWrapper[2] - currentWrapper[2]) >= 0.01 ||
        Math.abs(drawWrapper[3] - currentWrapper[3]) >= 0.01) return false;
    const targetDx = currentTarget[0] - drawTarget[0];
    const targetDy = currentTarget[1] - drawTarget[1];
    const wrapperDx = currentWrapper[0] - drawWrapper[0];
    const wrapperDy = currentWrapper[1] - drawWrapper[1];
    return Math.abs(targetDx - wrapperDx) < 0.01 && Math.abs(targetDy - wrapperDy) < 0.01 &&
      Math.abs((currentTarget[0] - currentWrapper[0]) - (drawTarget[0] - drawWrapper[0])) < 0.01 &&
      Math.abs((currentTarget[1] - currentWrapper[1]) - (drawTarget[1] - drawWrapper[1])) < 0.01;
  };
  const releaseSelection = expectedSlots => {
    const selected = new Set(expectedSlots);
    for (const [canvas, candidate] of candidates) if (selected.has(candidate.slot)) candidates.delete(canvas);
  };
  const clearWindow = () => {
    candidates.clear();
    proofs.clear();
    candidateSpread = null;
  };
  const safePath = value => typeof value === 'string' && /^\/episodes\/[0-9a-f]{13}$/.test(value)
    ? value : '<changed>';
  const safeRect = value => Array.isArray(value) && value.length === 4 && value.every(Number.isFinite)
    ? value.map(number => Math.round(number * 100) / 100) : null;
  const failureDetails = proof => {
    let layout = null;
    let current = null;
    try { layout = normalizedLayout(); } catch (_) { /* reported as unavailable */ }
    try { current = capture.inspect([]); } catch (_) { /* reported as unavailable */ }
    const pages = document.querySelector('#xCVPages');
    const viewer = document.querySelector('#comici-viewer');
    const seek = document.querySelector('#xCVSeekBar');
    const value = seek && Number.isSafeInteger(Number(seek.value)) ? Number(seek.value) : null;
    const slots = layout?.active ?? null;
    const summarizeSelected = row => {
      const children = pages ? [...pages.children] : [];
      const wrapper = children[row.slot] ?? null;
      const canvases = wrapper?.isConnected ? [...wrapper.querySelectorAll('canvas')] : [];
      const target = canvases.length === 1 ? canvases[0] : null;
      let state = null;
      let targetRect = null;
      let wrapperRect = null;
      let targetRectRaw = null;
      let wrapperRectRaw = null;
      let readbackAvailable = false;
      let contextMatches = null;
      let pixelsMatchProof = null;
      let replayMatchesProof = null;
      try {
        if (target) {
          state = canvasState(target);
          const rect = target.getBoundingClientRect();
          const parentRect = wrapper.getBoundingClientRect();
          targetRectRaw = [rect.x, rect.y, rect.width, rect.height];
          wrapperRectRaw = [parentRect.x, parentRect.y, parentRect.width, parentRect.height];
          targetRect = safeRect(targetRectRaw);
          wrapperRect = safeRect(wrapperRectRaw);
          const dimensionsMatchProof = target.width === row.width && target.height === row.height &&
            Number.isSafeInteger(row.width) && Number.isSafeInteger(row.height) &&
            row.width > 0 && row.height > 0 && row.width * row.height <= MAX_CANVAS_PIXELS &&
            safeDimensions(target, {width: row.width, height: row.height});
          readbackAvailable = target === row.target && wrapper === row.wrapper &&
            target.parentElement === row.candidate.holder && dimensionsMatchProof;
          if (readbackAvailable) {
            const context = Reflect.apply(raw.getContext, target, ['2d']);
            contextMatches = !!context && JSON.stringify(paint(context)) ===
              JSON.stringify(row.candidate.targetPaint);
            pixelsMatchProof = equalPixels(pixels(target), row.pixels);
            replayMatchesProof = equalPixels(replay(row.candidate), row.pixels);
          }
        }
      } catch (_) { /* each unavailable read remains false/null */ }
      const observed = current?.slots?.find(item => item.index === row.slot) ?? null;
      return {
        slot: row.slot,
        wrapperSame: !!wrapper && wrapper === row.wrapper,
        targetSame: !!target && target === row.target,
        holderSame: !!target && target.parentElement === row.candidate.holder,
        currentPhysicalSlot: wrapper ? children.indexOf(wrapper) : null,
        generation: state?.generation ?? null,
        writes: state?.writes ?? null,
        proofGeneration: row.generation,
        proofWrites: row.writes,
        generationMatches: state?.generation === row.generation,
        writesMatch: state?.writes === row.writes,
        width: target ? target.width : null,
        height: target ? target.height : null,
        proofWidth: row.width,
        proofHeight: row.height,
        targetRect: targetRect,
        wrapperRect: wrapperRect,
        proofTargetRect: safeRect(row.targetRect),
        proofWrapperRect: safeRect(row.wrapperRect),
        rectsSame: !!target && !!targetRect && !!wrapperRect &&
          !!targetRectRaw && !!wrapperRectRaw &&
          rectEqual(row.targetRect, targetRectRaw) && rectEqual(row.wrapperRect, wrapperRectRaw),
        ready: observed?.canvas?.ready === true,
        visible: observed?.canvas?.visible === true,
        centerInViewport: observed?.wrapperCenterInViewport === true,
        readbackAvailable,
        contextMatches,
        pixelsMatchProof,
        replayMatchesProof,
      };
    };
    const mutationReport = (() => {
      try { return capture.mutationsSince(proof.domGeneration); }
      catch (_) { return {available: false, complete: false, fromGeneration: proof.domGeneration,
        toGeneration: null, droppedCount: null, records: []}; }
    })();
    return {
      expected: {
        path: safePath(proof.episodePath), layoutVariant: proof.layoutVariant, seekValue: proof.expectedSeek,
        domGeneration: proof.domGeneration, captureDomGeneration: proof.captureDomGeneration,
        wrapperCount: proof.wrapperCount,
        activeSlots: proof.expectedSlots.slice(0, 2), viewport: proof.viewport,
      },
      observed: {
        path: safePath(location.pathname), layoutVariant: layout?.variant ?? null, seekValue: value,
        queryPresent: !!location.search, hashPresent: !!location.hash,
        layoutAvailable: !!layout,
        domGeneration: Number.isSafeInteger(current?.domGeneration) ? current.domGeneration : null,
        captureDomGeneration: Number.isSafeInteger(current?.captureDomGeneration)
          ? current.captureDomGeneration : null,
        viewerIdentity: viewer === proof.viewer, pagesIdentity: pages === proof.pages,
        seekIdentity: seek === proof.seek, wrapperCount: pages?.children.length ?? null,
        activeSlots: Array.isArray(slots) ? slots.slice(0, 2) : null,
        viewport: {width: innerWidth, height: innerHeight, dpr: devicePixelRatio},
      },
      selected: proof.selected.slice(0, 2).map(summarizeSelected),
      mutations: mutationReport,
    };
  };

  const api = {
    integrity() { return window.__younganimalViewerCapture === apiIdentity && capture.integrity(); },
    collect({expectedSlots, expectedSeek, episodePath, maxPngChars}) {
      const fallback = reason => {
        clearWindow();
        return {mode: 'fallback', reason};
      };
      if (!api.integrity()) return fallback('observer_integrity_lost');
      if (!Array.isArray(expectedSlots) || expectedSlots.length < 1 || expectedSlots.length > 2 ||
          typeof episodePath !== 'string') return fallback('invalid_expected_spread');
      let layout;
      try { layout = normalizedLayout(); } catch (_) { return fallback('viewer_layout_unavailable'); }
      if (!layout || location.pathname !== episodePath || location.search || location.hash ||
          layout.value !== expectedSeek || !sameArray(layout.active, expectedSlots))
        return fallback('selected_page_changed');
      const observation = capture.inspect(expectedSlots);
      const selected = [];
      try {
        for (const slot of expectedSlots) {
          const wrapper = layout.children[slot];
          const canvases = wrapper ? [...wrapper.querySelectorAll('canvas')] : [];
          const target = canvases.length === 1 ? canvases[0] : null;
          const candidate = target ? candidates.get(target) : null;
          if (!target || !candidate || candidate.slot !== slot || candidate.target !== target ||
              candidate.wrapper !== wrapper || candidate.holder !== target.parentElement ||
              candidate.pages !== layout.pages || candidate.viewer !== layout.viewer ||
              candidate.seek !== layout.seek || candidate.episodePath !== episodePath ||
              candidate.layoutVariant !== layout.variant ||
              !sameArray(candidate.roles, layout.roles) ||
              candidate.seekValue !== layout.value || !sameArray(candidate.activeSlots, expectedSlots) ||
              candidate.targetWidth !== target.width ||
              candidate.targetHeight !== target.height || clipUnsafe.has(target) ||
              target.parentElement?.classList.contains('-cv-page-canvas') !== true ||
              target.parentElement.querySelectorAll('canvas').length !== 1 ||
              !wrapper.classList.contains('mode-loaded') || !wrapper.classList.contains('mode-rendered') ||
              !safeDimensions(target) || !safeDimensions(candidate.snapshot) || candidate.snapshot.isConnected)
            return fallback('native_candidate_missing_or_stale');
          const state = canvasState(target);
          if (state.generation !== candidate.targetAfter.generation ||
              state.writes !== candidate.targetAfter.writes) return fallback('native_target_write_changed');
          const currentPaint = paint(Reflect.apply(raw.getContext, target, ['2d']));
          if (!paintSupported(candidate.targetPaint) || !paintSupported(currentPaint) ||
              JSON.stringify(currentPaint) !== JSON.stringify(candidate.targetPaint) ||
              !attrsEqual(candidate.snapshotAttributes, candidate.sourceAttrs))
            return fallback('native_context_state_unsupported');
          const targetRect = target.getBoundingClientRect();
          const wrapperRect = wrapper.getBoundingClientRect();
          const targetPixels = pixels(target);
          const replayPixels = replay(candidate);
          if (!equalPixels(targetPixels, replayPixels)) return fallback('native_replay_pixel_mismatch');
          const row = observation.slots[slot];
          if (!row?.canvas?.ready || !row.canvas.visible || !row.wrapperCenterInViewport ||
              row.canvas.pixelError || !rectPureTranslation(
                candidate.targetRect, candidate.wrapperRect,
                [targetRect.x, targetRect.y, targetRect.width, targetRect.height],
                [wrapperRect.x, wrapperRect.y, wrapperRect.width, wrapperRect.height]))
            return fallback('native_target_layout_changed');
          selected.push({slot, wrapper, target, candidate, state,
            pixels: new Uint8ClampedArray(targetPixels), observation: row,
            targetRect: [targetRect.x, targetRect.y, targetRect.width, targetRect.height],
            wrapperRect: [wrapperRect.x, wrapperRect.y, wrapperRect.width, wrapperRect.height]});
        }
        const wholePixels = selected.reduce((sum, row) => sum + row.pixels.length / 4, 0);
        if (wholePixels > MAX_SPREAD_PIXELS) return fallback('native_spread_pixel_limit');
      } catch (_) { return fallback('native_proof_unavailable'); }

      proofs.clear();
      const token = `ya${nextProof++}`;
      const proof = {token, episodePath, expectedSeek, expectedSlots: expectedSlots.slice(),
        layoutVariant: layout.variant,
        roles: layout.roles.slice(),
        pages: layout.pages, viewer: layout.viewer, seek: layout.seek,
        domGeneration: layout.dom, captureDomGeneration: layout.captureDom,
        viewport: layout.viewport, wrapperCount: layout.children.length,
        selected: selected.map(row => ({...row, generation: row.state.generation,
          writes: row.state.writes, width: row.target.width, height: row.target.height,
          snapshot: row.candidate.snapshot, sourceWidth: row.candidate.sourceWidth,
          sourceHeight: row.candidate.sourceHeight,
          snapshotAttributes: row.candidate.snapshotAttributes}))};
      proofs.set(token, proof);
      releaseSelection(expectedSlots);
      const images = [];
      try {
        for (const row of proof.selected) {
          const encoded = Reflect.apply(raw.toDataURL, row.snapshot, ['image/png']);
          if (typeof encoded !== 'string' || !encoded.startsWith('data:image/png;base64,') ||
              encoded.length > maxPngChars) throw new Error('native_png_readback_invalid');
          images.push({slot: row.slot, width: row.sourceWidth, height: row.sourceHeight, png: encoded,
            targetWidth: row.width, targetHeight: row.height, generation: row.generation,
            writes: row.writes, sourceWidth: row.sourceWidth, sourceHeight: row.sourceHeight,
            sourceGeneration: row.candidate.sourceState.generation,
            sourceWrites: row.candidate.sourceState.writes});
        }
      } catch (_) { return {mode: 'selected_error', token, reason: 'native_png_readback_failed'}; }
      return {mode: 'native', token, images, observation};
    },
    verify(token) {
      const proof = proofs.get(token);
      proofs.delete(token);
      if (!proof) return {ok: false, reason: 'native_proof_missing'};
      const fail = reason => {
        let details = null;
        try { details = failureDetails(proof); } catch (_) { /* keep the original fail-closed result */ }
        return {ok: false, reason, details};
      };
      try {
        if (!api.integrity() || location.pathname !== proof.episodePath || location.search || location.hash ||
            document.querySelector('#xCVPages') !== proof.pages ||
            document.querySelector('#comici-viewer') !== proof.viewer ||
            document.querySelector('#xCVSeekBar') !== proof.seek) return fail('native_reader_identity_changed');
        const layout = normalizedLayout();
        if (!layout || layout.path !== proof.episodePath || layout.value !== proof.expectedSeek ||
            layout.variant !== proof.layoutVariant ||
            !sameArray(layout.roles, proof.roles) ||
            layout.captureDom !== proof.captureDomGeneration || layout.pages !== proof.pages || layout.viewer !== proof.viewer ||
            layout.seek !== proof.seek || layout.children.length !== proof.wrapperCount ||
            !sameArray(layout.active, proof.expectedSlots) ||
            layout.viewport.width !== proof.viewport.width || layout.viewport.height !== proof.viewport.height ||
            layout.viewport.dpr !== proof.viewport.dpr) return fail('native_reader_layout_changed');
        if (proof.selected.length !== proof.expectedSlots.length) return fail('native_proof_incomplete');
        for (const row of proof.selected) {
          const wrapper = layout.children[row.slot];
          const nodes = wrapper ? [...wrapper.querySelectorAll('canvas')] : [];
          const target = nodes.length === 1 ? nodes[0] : null;
          if (wrapper !== row.wrapper || target !== row.target || target.parentElement !== row.candidate.holder ||
              !wrapper.classList.contains('mode-loaded') || !wrapper.classList.contains('mode-rendered'))
            return fail('native_target_replaced');
          const state = canvasState(target);
          if (state.generation !== row.generation || state.writes !== row.writes)
            return fail('native_target_generation_or_write_changed');
          if (target.width !== row.width || target.height !== row.height) return fail('native_target_dimensions_changed');
          const rect = target.getBoundingClientRect();
          const wrapperRect = wrapper.getBoundingClientRect();
          if (!rectEqual(row.targetRect, [rect.x, rect.y, rect.width, rect.height]) ||
              !rectEqual(row.wrapperRect, [wrapperRect.x, wrapperRect.y, wrapperRect.width, wrapperRect.height]))
            return fail('native_target_layout_changed');
          const observed = capture.inspect([]).slots[row.slot];
          if (!observed?.canvas?.ready || !observed.canvas.visible || !observed.wrapperCenterInViewport ||
              observed.canvas.node !== row.observation.canvas.node ||
              observed.wrapperNode !== row.observation.wrapperNode ||
              observed.canvas.generation !== row.generation || observed.canvas.writes !== row.writes)
            return fail('native_target_readiness_changed');
          if (!equalPixels(pixels(target), row.pixels)) return fail('native_target_pixels_changed');
          if (row.snapshot.isConnected || row.snapshot.width !== row.sourceWidth || row.snapshot.height !== row.sourceHeight ||
              !attrsEqual(attr(Reflect.apply(raw.getContext, row.snapshot, ['2d'])), row.snapshotAttributes))
            return fail('native_snapshot_identity_changed');
        }
        return {ok: true, observation: capture.inspect(proof.expectedSlots)};
      } catch (_) { return fail('native_postproof_unavailable'); }
    },
    release({token, expectedSlots, clearAll = false}) {
      if (clearAll) {
        // Cancellation or a lost selection result can hide the single-use token.
        clearWindow();
      } else {
        if (typeof token === 'string') proofs.delete(token);
        if (Array.isArray(expectedSlots)) releaseSelection(expectedSlots);
      }
      return {candidateCount: candidates.size, proofCount: proofs.size};
    },
    status() { return {candidateCount: candidates.size, proofCount: proofs.size, integrity: api.integrity()}; },
  };
  window.__younganimalNativeCapture = api;
  addEventListener('pagehide', () => { candidates.clear(); proofs.clear(); unregister(); }, {once: true});
  } catch (error) {
    window.__younganimalNativeCaptureInitError = String(error?.name || 'Error') + ':' + String(error?.message || '');
  }
})()"""

COLLECT_CAPTURE_SCRIPT = r"""args => {
  const api = window.__younganimalNativeCapture;
  if (!api || typeof api.collect !== 'function') return {mode: 'fallback',
    reason: `native_observer_missing:${window.__younganimalNativeCaptureInitError || 'not_installed'}`};
  return api.collect(args);
}"""

VERIFY_CAPTURE_SCRIPT = r"""token => {
  const api = window.__younganimalNativeCapture;
  if (!api || typeof api.verify !== 'function') return {ok: false, reason: 'native_observer_missing'};
  return api.verify(token);
}"""

RELEASE_CAPTURE_SCRIPT = r"""args => {
  const api = window.__younganimalNativeCapture;
  if (!api || typeof api.release !== 'function') return null;
  return api.release(args);
}"""


@dataclass(frozen=True, slots=True)
class NativeImage:
    slot: int
    width: int
    height: int
    png: bytes
    target_width: int
    target_height: int
    generation: int
    writes: int
    source_generation: int
    source_writes: int


def decode_native_images(value: object, *, expected_slots: tuple[int, ...]) -> tuple[NativeImage, ...]:
    if not isinstance(value, list) or len(value) != len(expected_slots):
        raise UnknownPageStateError("Younganimal native image spread is incomplete")
    images: list[NativeImage] = []
    total_pixels = 0
    total_bytes = 0
    prefix = "data:image/png;base64,"
    for expected, item in zip(expected_slots, value, strict=True):
        if not isinstance(item, dict) or item.get("slot") != expected:
            raise UnknownPageStateError("Younganimal native image order changed")
        width, height = item.get("width"), item.get("height")
        numeric = ("targetWidth", "targetHeight", "generation", "writes", "sourceGeneration", "sourceWrites")
        if (
            type(width) is not int or type(height) is not int or width <= 0 or height <= 0
            or width * height > MAX_CANVAS_PIXELS
            or type(item.get("slot")) is not int
            or type(item.get("sourceWidth")) is not int or item["sourceWidth"] != width
            or type(item.get("sourceHeight")) is not int or item["sourceHeight"] != height
            or any(type(item.get(name)) is not int or item[name] < 0 for name in numeric)
            or item.get("targetWidth", 0) <= 0 or item.get("targetHeight", 0) <= 0
            or item.get("targetWidth", 0) * item.get("targetHeight", 0) > MAX_CANVAS_PIXELS
            or item.get("writes", 0) < 1 or item.get("sourceWrites", 0) < 1
        ):
            raise UnknownPageStateError("Younganimal native dimensions or draw proof is invalid")
        encoded = item.get("png")
        if not isinstance(encoded, str) or not encoded.startswith(prefix) or len(encoded) > len(prefix) + 4 * ((MAX_IMAGE_BYTES + 2) // 3):
            raise UnknownPageStateError("Younganimal native PNG readback is malformed or oversized")
        try:
            data = base64.b64decode(encoded.partition(",")[2], validate=True)
        except (binascii.Error, ValueError) as exc:
            raise UnknownPageStateError("Younganimal native PNG base64 is malformed") from exc
        if len(data) > MAX_IMAGE_BYTES:
            raise UnknownPageStateError("Younganimal native PNG exceeds its byte bound")
        try:
            with Image.open(io.BytesIO(data)) as image:
                if image.format != "PNG" or image.size != (width, height) or getattr(image, "n_frames", 1) != 1:
                    raise UnknownPageStateError("Younganimal native PNG format or dimensions changed")
                image.verify()
            with Image.open(io.BytesIO(data)) as image:
                image.load()
                if image.convert("RGBA").size != (width, height):
                    raise UnknownPageStateError("Younganimal native PNG pixel dimensions changed")
        except (UnidentifiedImageError, OSError, ValueError) as exc:
            if isinstance(exc, UnknownPageStateError):
                raise
            raise UnknownPageStateError("Younganimal native PNG did not decode cleanly") from exc
        total_pixels += width * height
        total_bytes += len(data)
        if total_pixels > MAX_SPREAD_PIXELS or total_bytes > MAX_IMAGE_BYTES * MAX_CANDIDATES:
            raise UnknownPageStateError("Younganimal native spread exceeds its bounds")
        images.append(NativeImage(
            expected, width, height, data, item["targetWidth"], item["targetHeight"],
            item["generation"], item["writes"], item["sourceGeneration"], item["sourceWrites"],
        ))
    return tuple(images)


def encode_native_webp(images: tuple[NativeImage, ...]) -> tuple[CaptureResult, ...]:
    """Encode verified native snapshots only as exact lossless VP8L WebP."""
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
        except Exception:  # noqa: BLE001 - preserve the verified native PNG on encoder failures
            results.append(fallback)
    return tuple(results)


def _png_result(item: NativeImage) -> CaptureResult:
    return CaptureResult(item.png, item.width, item.height, "image/png", ".png")


def _single_vp8l(data: bytes, *, width: int, height: int) -> bool:
    if (
        len(data) < 25 or data[:4] != b"RIFF" or int.from_bytes(data[4:8], "little") != len(data) - 8
        or data[8:12] != b"WEBP" or data[12:16] != b"VP8L"
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


__all__ = [
    "COLLECT_CAPTURE_SCRIPT",
    "MAX_CANDIDATES",
    "MAX_CANVAS_PIXELS",
    "MAX_IMAGE_BYTES",
    "MAX_SPREAD_PIXELS",
    "OBSERVER_INIT_SCRIPT",
    "RELEASE_CAPTURE_SCRIPT",
    "VERIFY_CAPTURE_SCRIPT",
    "NativeImage",
    "decode_native_images",
    "encode_native_webp",
]
