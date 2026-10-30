"""Adapter for the BookWalker image/canvas browser viewer.

The viewer shell is a canvas renderer. This adapter intentionally uses only
stable DOM signals exposed by the viewer shell and stops on ambiguous states.
"""

from __future__ import annotations

import asyncio
import base64
import copy
import hashlib
import json
import math
import os
import re
import time
from binascii import Error as BinasciiError
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, ClassVar
from urllib.parse import parse_qs, urlparse
from uuid import uuid4

from playwright.async_api import Error as PlaywrightError
from playwright.async_api import Locator, Page
from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from screenshot_crawler.core.access_guard import AccessProfile
from screenshot_crawler.core.capture import CaptureResult, capture_png_bytes
from screenshot_crawler.core.errors import (
    CaptureUnavailableError,
    PageChangeTimeoutError,
    UnknownPageStateError,
    UnsupportedAccessStrategyError,
)
from screenshot_crawler.core.models import AccessStrategy, ContentContext, ContentIdentity
from screenshot_crawler.core.state import PageState
from screenshot_crawler.site_adapters.base import SiteAdapter
from screenshot_crawler.site_adapters.bookwalker.access import bookwalker_access_profile
from screenshot_crawler.site_adapters.bookwalker.login import (
    BookWalkerLoginError,
    is_bookwalker_login_page,
    login_bookwalker,
    submit_bookwalker_login_form,
)
from screenshot_crawler.site_adapters.bookwalker.lossless_jpeg import (
    LosslessJpegResult,
    reconstruct_lossless_jpeg,
)
from screenshot_crawler.site_adapters.bookwalker.native_capture import select_native_draw_calls
from screenshot_crawler.site_adapters.bookwalker.original_capture import (
    MAX_RESPONSE_BODY_BYTES,
    OriginalJpegCache,
    candidate_capture,
    candidate_from_jpeg,
    image_signature,
    imagebitmap_pixel_exact_match,
    imagebitmap_signature,
    is_reconstruction_jpeg_candidate,
)
from screenshot_crawler.site_adapters.bookwalker.purchased_mapping import (
    MappingAnalysis,
    analyze_purchased_mapping,
    decode_compact_completed_mappings,
    resolve_scaled_canvas_source_candidate,
    validate_scaled_canvas_source_analysis,
)
from screenshot_crawler.site_adapters.bookwalker.reader_controls import (
    ReaderControlKind,
    classify_reader_control,
    is_reader_control_candidate,
)
from screenshot_crawler.site_adapters.bookwalker.terminal_match import (
    TERMINAL_DESCRIPTOR_SCRIPT,
    decode_terminal_data_url,
    describe_terminal_png,
    match_terminal_descriptor,
)

_DRAW_TRACE_SCRIPT = """
(() => {
  if (window.__bookwalkerDrawTraceInstalled) return;
  window.__bookwalkerDrawTraceInstalled = true;
  window.__bookwalkerDrawCalls = [];
  window.__bookwalkerCaptureMode = window.__bookwalkerCaptureMode || 'native';
  window.__bookwalkerNativeCaptureEnabled =
    window.__bookwalkerCaptureMode === 'native';
  window.__bookwalkerDirectOriginalEnabled =
    window.__bookwalkerDirectOriginalEnabled === true;
  window.__bookwalkerNativeDrawCalls = [];
  window.__bookwalkerNativeSourceObjects = new Map();
  window.__bookwalkerNativeSnapshots = new Map();
  window.__bookwalkerNativeCaptureDiagnostics = {
    nativeCallsSeen: 0,
    nativeCallsAdmitted: 0,
    nativeCallsRetained: 0,
    nativeCallsEvicted: 0,
    definitelySmallCallsDropped: 0,
    geometrySmallCallsDropped: 0,
    executedFullClearWitnessCount: 0,
    rejectedFullClearWitnessCount: 0,
  };
  window.__bookwalkerResetNativeCaptureDiagnostics = () => {
    window.__bookwalkerNativeCaptureDiagnostics = {
      nativeCallsSeen: 0,
      nativeCallsAdmitted: 0,
      nativeCallsRetained: 0,
      nativeCallsEvicted: 0,
      definitelySmallCallsDropped: 0,
      geometrySmallCallsDropped: 0,
      executedFullClearWitnessCount: 0,
      rejectedFullClearWitnessCount: 0,
    };
  };
  // A direct one-hop record is deliberately separate from the tiled native
  // mapping.  The cover path is a single ImageBitmap -> canvas copy followed
  // by one canvas -> renderer draw.  Keep object references and canvas copies
  // here; materialization/PNG encoding happens after the draw hook returns.
  window.__bookwalkerDirectOneHopRecords = [];
  window.__bookwalkerDirectOneHopSnapshots = new Map();
  let nextDirectOneHopToken = 1;
  let directOneHopSnapshotBytes = 0;
  const directGeometryVersions = new WeakMap();
  const directGeometryEvictedCanvasIds = new Set();
  const DIRECT_GEOMETRY_LEDGER_LIMIT = 8192;
  let directGeometryHistoryEvictions = 0;
  window.__bookwalkerDirectOneHopToken = String(nextDirectOneHopToken++);
  window.__bookwalkerResetDirectOneHop = () => {
    window.__bookwalkerDirectOneHopRecords = [];
    window.__bookwalkerDirectOneHopSnapshots.clear();
    directOneHopSnapshotBytes = 0;
    window.__bookwalkerDirectOneHopToken = String(nextDirectOneHopToken++);
  };
  const directGeometryVersionFor = canvas => Number(
    directGeometryVersions.get(canvas) || 0,
  );
  const directGeometryHistoryIncompleteFor = canvas => (
    Boolean(canvas) && directGeometryEvictedCanvasIds.has(getCanvasId(canvas))
  );

  // These bounds replace the old global operation-list limit.  16,384 tile
  // records cover normal pages and 4K-class 32x32 tile grids with room for
  // renderer variation; pathological segments fail closed instead of growing
  // renderer-critical memory without bound.
  const MAX_ACTIVE_SEGMENTS = 8;
  const MAX_TILE_DRAWS_PER_SEGMENT = 16384;
  const MAX_COMPLETED_MAPPINGS = 12;
  const MAX_COMPLETED_TILE_RECORDS = 20000;
  const MAX_NON_IMAGE_BITMAP_DRAW_RECORDS = 4;
  const FULL_CLEAR_EPSILON = 1e-7;
  const original = CanvasRenderingContext2D.prototype.drawImage;
  let nextCanvasId = 1;
  let nextSourceId = 1;
  const canvasIds = new WeakMap();
  const sourceIds = new WeakMap();
  const canvasResetEpochs = new WeakMap();
  const canvasUnknownMutations = new WeakSet();
  const knownAttributeMutations = new WeakMap();
  const canvasMutationObservers = new WeakMap();
  const canvasMutationObserverStates = new WeakMap();
  const canvasContentVersions = new WeakMap();
  const contextSafetyUnknown = new WeakMap();
  const contextStates = new WeakMap();
  const canvasContexts = new WeakMap();
  const contextLossObserved = new WeakSet();
  const internalCanvases = new WeakSet();
  window.__bookwalkerCanvasResetObservationAvailable = false;
  window.__bookwalkerMarkInternalCanvas = canvas => {
    if (canvas) internalCanvases.add(canvas);
  };

  let transformTraceEpoch = 0;
  const newTrace = () => ({
    traceEpoch: ++transformTraceEpoch,
    nextOperationIndex: 0,
    activeSegments: {},
    completedMappings: [],
    droppedActiveSegmentCount: 0,
    droppedCompletedMappingCount: 0,
    evictedCanvasIds: [],
    diagnostics: {
      observedOperationCount: 0,
      drawImageCount: 0,
      clearRectCount: 0,
      executedFullClearWitnessCount: 0,
      rejectedFullClearWitnessCount: 0,
      unsafeOperationCount: 0,
        canvasResetObservationAvailable: window.__bookwalkerCanvasResetObservationAvailable === true,
        canvasResetFailureCount: 0,
        unknownCanvasMutationCount: 0,
    },
  });
  window.__bookwalkerTransformTrace = newTrace();
  window.__bookwalkerResetTransformTrace = () => {
    window.__bookwalkerTransformTrace = newTrace();
  };

  const getCanvasId = canvas => {
    let id = canvasIds.get(canvas);
    if (!id) {
      id = String(nextCanvasId++);
      canvasIds.set(canvas, id);
      try { canvas.dataset.bookwalkerTraceId = id; } catch (error) {}
    }
    return id;
  };
  // Read-only identity export for diagnostics; it is backed by the actual
  // WeakMap object identity rather than a mutable DOM data attribute.
  window.__bookwalkerCanvasIdentity = canvas => canvas ? getCanvasId(canvas) : null;
  window.__bookwalkerCanvasResetEpoch = canvas => (
    canvas ? Number(canvasResetEpochs.get(canvas) || 0) : null
  );
  const contentVersion = canvas => Number(canvasContentVersions.get(canvas) || 0);
  const advanceContentVersion = canvas => {
    if (!canvas) return 0;
    const next = contentVersion(canvas) + 1;
    canvasContentVersions.set(canvas, next);
    return next;
  };
  const ensureContextState = context => {
    if (!context) return null;
    let state = contextStates.get(context);
    if (!state) {
      state = {
        knownNoClip: (canvasResetEpochs.get(context.canvas) || 0) > 0,
        saveStack: [],
      };
      contextStates.set(context, state);
      const canvas = context.canvas;
      const contexts = canvasContexts.get(canvas) || new Set();
      contexts.add(context);
      canvasContexts.set(canvas, contexts);
    }
    return state;
  };
  const markContextKnownFresh = context => {
    const state = ensureContextState(context);
    if (!state) return;
    state.knownNoClip = true;
    state.saveStack = [];
    contextSafetyUnknown.delete(context);
  };
  const markCanvasContextsKnownFresh = canvas => {
    for (const context of canvasContexts.get(canvas) || []) {
      markContextKnownFresh(context);
    }
  };
  const contextSafetyInfo = context => {
    const state = ensureContextState(context);
    return state ? {
      knownNoClip: state.knownNoClip === true,
      saveStackKnown: state.knownNoClip === true,
      saveStackDepth: state.saveStack.length,
    } : null;
  };
  const observeContextLoss = canvas => {
    if (!canvas || contextLossObserved.has(canvas)
        || typeof canvas.addEventListener !== 'function') return;
    try {
      canvas.addEventListener('contextlost', () => {
        const trace = window.__bookwalkerTransformTrace;
        directRecordMutation(canvas, Number(trace?.nextOperationIndex || 0) + 1, 'contextlost');
        advanceContentVersion(canvas);
      });
      contextLossObserved.add(canvas);
    } catch (error) {}
  };
  const getSourceId = source => {
    let id = sourceIds.get(source);
    if (!id) {
      id = String(nextSourceId++);
      sourceIds.set(source, id);
    }
    window.__bookwalkerNativeSourceObjects.set(id, source);
    while (window.__bookwalkerNativeSourceObjects.size > 120) {
      const oldest = window.__bookwalkerNativeSourceObjects.keys().next().value;
      window.__bookwalkerNativeSourceObjects.delete(oldest);
    }
    return id;
  };
  const sourceRectAndDestination = (source, values) => {
    const width = Number.isFinite(source?.width) ? Number(source.width) : null;
    const height = Number.isFinite(source?.height) ? Number(source.height) : null;
    if (values.length === 2 && width !== null && height !== null) {
      return {
        sourceRect: {x: 0, y: 0, width, height},
        destination: {x: values[0], y: values[1], width, height},
      };
    }
    if (values.length === 4) {
      return {
        sourceRect: width === null || height === null
          ? null : {x: 0, y: 0, width, height},
        destination: {
          x: values[0], y: values[1], width: values[2], height: values[3],
        },
      };
    }
    if (values.length === 8) {
      return {
        sourceRect: {
          x: values[0], y: values[1], width: values[2], height: values[3],
        },
        destination: {
          x: values[4], y: values[5], width: values[6], height: values[7],
        },
      };
    }
    return {sourceRect: null, destination: null};
  };
  // Keep only rectangles that are definitely unselectable out of the native
  // candidate pool. Fractional, clipped, negative, and otherwise uncertain
  // rectangles remain for the authoritative Python selector to decide.
  const definitelySmallNativeDestination = destination => {
    if (!destination) return false;
    const values = [destination.x, destination.y, destination.width, destination.height]
      .map(value => Number(value));
    if (!values.every(Number.isFinite)) return false;
    const [, , width, height] = values;
    if (width < 0 || height < 0
        || !Number.isInteger(width) || !Number.isInteger(height)) return false;
    return width < 100 || height < 100;
  };
  const readTransform = context => {
    try {
      const matrix = context.getTransform();
      return {
        a: matrix.a, b: matrix.b, c: matrix.c,
        d: matrix.d, e: matrix.e, f: matrix.f,
      };
    } catch (error) {
      return null;
    }
  };
  const traceSourceInfo = source => {
    if (!source) return null;
    const constructor = source?.constructor?.name || null;
    const info = {
      sourceId: getSourceId(source),
      constructor,
      width: Number.isFinite(source?.width) ? Number(source.width) : null,
      height: Number.isFinite(source?.height) ? Number(source.height) : null,
      contentVersion: constructor === 'HTMLCanvasElement'
        ? contentVersion(source) : null,
    };
    if (constructor === 'HTMLCanvasElement') {
      info.canvasId = getCanvasId(source);
      info.sourceCanvasId = info.canvasId;
      info.resetEpoch = canvasResetEpochs.get(source) || 0;
    }
    return info;
  };
  const targetInfo = canvas => ({
    canvasId: getCanvasId(canvas),
    constructor: canvas?.constructor?.name || null,
    width: Number(canvas?.width),
    height: Number(canvas?.height),
    resetEpoch: canvasResetEpochs.get(canvas) || 0,
    contentVersion: contentVersion(canvas),
  });
  const recordOperation = (operationName, context, details = {}) => {
    const trace = window.__bookwalkerTransformTrace;
    if (!trace || window.__bookwalkerCaptureMode !== 'native') return null;
    const canvas = context?.canvas;
    if (!canvas) return null;
    if (internalCanvases.has(canvas)) return null;
    observeContextLoss(canvas);
    flushCanvasMutationObserver(canvas);
    const index = ++trace.nextOperationIndex;
    trace.diagnostics.observedOperationCount = index;
    trace.diagnostics[`${operationName}Count`] =
      (trace.diagnostics[`${operationName}Count`] || 0) + 1;
    const operation = {
      index,
      operation: operationName,
      traceEpoch: trace.traceEpoch,
      target: targetInfo(canvas),
      transform: readTransform(context),
      globalAlpha: Number.isFinite(context.globalAlpha)
        ? Number(context.globalAlpha) : null,
      globalCompositeOperation: context.globalCompositeOperation || null,
      filter: context.filter || null,
      shadowBlur: Number.isFinite(context.shadowBlur) ? Number(context.shadowBlur) : null,
      shadowColor: context.shadowColor || null,
      shadowOffsetX: Number.isFinite(context.shadowOffsetX) ? Number(context.shadowOffsetX) : null,
      shadowOffsetY: Number.isFinite(context.shadowOffsetY) ? Number(context.shadowOffsetY) : null,
      contextSafety: contextSafetyInfo(context),
      ...details,
    };
    directRecordMutation(canvas, index, operationName, operation);
    return operation;
  };
  const isSafeDraw = operation => {
    const transform = operation?.transform;
    return !!transform
      && transform.a === 1 && transform.b === 0
      && transform.c === 0 && transform.d === 1
      && transform.e === 0 && transform.f === 0
      && (operation.globalAlpha === 1 || operation.globalAlpha === 1.0)
      && operation.globalCompositeOperation === 'source-over'
      && operation.filter === 'none';
  };
  const isFullClear = (canvas, rectangle) => {
    if (!rectangle || !canvas) return false;
    const close = (left, right) => Math.abs(Number(left) - Number(right)) <= FULL_CLEAR_EPSILON;
    return close(rectangle.x, 0) && close(rectangle.y, 0)
      && close(rectangle.width, canvas.width)
      && close(rectangle.height, canvas.height);
  };
  const hasPrimitiveFiniteFullClearArguments = (canvas, args) => (
    Array.isArray(args) && args.length === 4
    && args.every(value => typeof value === 'number' && Number.isFinite(value))
    && args[0] === 0 && args[1] === 0
    && args[2] === canvas.width && args[3] === canvas.height
  );
  const identityTransform = transform => Boolean(transform)
    && transform.a === 1 && transform.b === 0
    && transform.c === 0 && transform.d === 1
    && transform.e === 0 && transform.f === 0;
  const contextLostState = context => {
    if (!context || typeof context.isContextLost !== 'function') {
      return {available: false, value: null};
    }
    try {
      const value = context.isContextLost();
      return typeof value === 'boolean'
        ? {available: true, value}
        : {available: false, value: null};
    } catch (error) {
      return {available: false, value: null};
    }
  };
  const markUnsafe = (canvas, operationIndex, type) => {
    const trace = window.__bookwalkerTransformTrace;
    const segment = trace?.activeSegments?.[getCanvasId(canvas)];
    if (!segment) return;
    segment.unsafeOperationCount += 1;
    segment.firstUnsafeOperationIndex ??= operationIndex;
    if (!segment.unsafeOperationTypes.includes(type)) {
      segment.unsafeOperationTypes.push(type);
    }
    if (trace?.diagnostics) trace.diagnostics.unsafeOperationCount += 1;
  };
  const newSegment = (
    canvas, operationIndex, rectangle, resetKind = 'clearRect', resetEpoch = null,
  ) => {
    const trace = window.__bookwalkerTransformTrace;
    const canvasId = getCanvasId(canvas);
    const active = trace.activeSegments;
    if (!active[canvasId] && Object.keys(active).length >= MAX_ACTIVE_SEGMENTS) {
      let oldestId = null;
      let oldestIndex = Infinity;
      for (const [id, candidate] of Object.entries(active)) {
        if (candidate.clearOperationIndex < oldestIndex) {
          oldestId = id;
          oldestIndex = candidate.clearOperationIndex;
        }
      }
      if (oldestId !== null) {
        delete active[oldestId];
        trace.droppedActiveSegmentCount += 1;
        trace.evictedCanvasIds.push(oldestId);
        if (trace.evictedCanvasIds.length > 32) trace.evictedCanvasIds.shift();
      }
    }
    active[canvasId] = {
      clearOperationIndex: operationIndex,
      clearRectangle: rectangle,
      target: targetInfo(canvas),
      clearTarget: targetInfo(canvas),
      resetObservationAvailable: false,
      mutationObserverAvailable: false,
      mutationObserverTakeRecordsAvailable: false,
      resetKind,
      resetEpoch: resetEpoch ?? (canvasResetEpochs.get(canvas) || 0),
      tileTarget: null,
      unknownMutation: canvasUnknownMutations.has(canvas),
      tileDraws: [],
      sourceIds: [],
      unsafeOperationCount: 0,
      firstUnsafeOperationIndex: null,
      unsafeOperationTypes: [],
      nonImageBitmapDraws: [],
      overflow: false,
      expectedTileCount: null,
    };
    return active[canvasId];
  };
  const recordExecutedFullClearWitness = (
    context, args, operation, observerState, flushedBefore,
    transformBefore, safetyBefore, lostBefore, contentVersionBefore,
    resetEpochBefore, traceEpochBefore, dimensionsBefore,
    unknownMutationBefore,
  ) => {
    const canvas = context?.canvas;
    const trace = window.__bookwalkerTransformTrace;
    if (!canvas || !trace || !operation) return false;
    const observerFlushedAfter = flushCanvasMutationObserver(canvas);
    const transformAfter = readTransform(context);
    const safetyAfter = contextSafetyInfo(context);
    const lostAfter = contextLostState(context);
    const dimensionsAfter = {
      width: Number(canvas.width), height: Number(canvas.height),
    };
    const resetEpochAfter = Number(canvasResetEpochs.get(canvas) || 0);
    const contentVersionAfter = contentVersion(canvas);
    const canvasId = getCanvasId(canvas);
    const resetObservationAvailable =
      window.__bookwalkerCanvasResetObservationAvailable === true;
    const segment = trace.activeSegments?.[canvasId];
    const unknownBefore = unknownMutationBefore === true;
    const unknownAfter = canvasUnknownMutations.has(canvas);
    const reasons = [];
    if (!hasPrimitiveFiniteFullClearArguments(canvas, args)) reasons.push('arguments');
    if (!isFullClear(canvas, operation.relevantRectangle)) reasons.push('rectangle');
    if (!identityTransform(transformBefore) || !identityTransform(transformAfter)) {
      reasons.push('transform');
    }
    if (!safetyBefore?.knownNoClip || !safetyBefore?.saveStackKnown
        || !safetyAfter?.knownNoClip || !safetyAfter?.saveStackKnown) {
      reasons.push('context_safety');
    }
    if (!lostBefore.available || lostBefore.value || !lostAfter.available || lostAfter.value) {
      reasons.push('context_lost');
    }
    if (!observerState?.available || !observerState?.takeRecordsAvailable
        || !flushedBefore || !observerFlushedAfter) {
      reasons.push('observer');
    }
    if (trace.traceEpoch !== traceEpochBefore) reasons.push('trace_epoch');
    if (resetEpochBefore !== resetEpochAfter) reasons.push('reset_epoch');
    if (dimensionsBefore.width !== dimensionsAfter.width
        || dimensionsBefore.height !== dimensionsAfter.height) reasons.push('dimensions');
    if (contentVersionAfter <= contentVersionBefore) reasons.push('content_version');
    if (trace.nextOperationIndex !== operation.index) reasons.push('reentrant_operation');
    if (!resetObservationAvailable) reasons.push('reset_observation');
    if (operation.target?.canvasId !== canvasId) reasons.push('target_canvas');
    if (unknownBefore || unknownAfter || canvasUnknownMutations.has(canvas)) {
      reasons.push('unknown_mutation');
    }
    if (!segment || segment.clearOperationIndex !== operation.index) reasons.push('segment');
    if (reasons.length) {
      trace.diagnostics.rejectedFullClearWitnessCount += 1;
      const nativeDiagnostics = window.__bookwalkerNativeCaptureDiagnostics;
      if (nativeDiagnostics) nativeDiagnostics.rejectedFullClearWitnessCount += 1;
      if (segment) {
        segment.executedFullClearWitnessRejection = {
          version: 1,
          operationIndex: operation.index,
          reasons: [...new Set(reasons)],
        };
      }
      return false;
    }
    const witness = {
      version: 1,
      kind: 'executed_full_clear',
      operationIndex: operation.index,
      canvasId,
      traceEpoch: traceEpochBefore,
      resetEpoch: resetEpochAfter,
      dimensionsBefore,
      dimensionsAfter,
      clearRectangle: {...operation.relevantRectangle},
      transformBefore,
      transformAfter,
      contextSafetyBefore: safetyBefore,
      contextSafetyAfter: safetyAfter,
      contextLostBefore: lostBefore.value,
      contextLostAfter: lostAfter.value,
      observerAvailable: observerState.available === true,
      takeRecordsAvailable: observerState.takeRecordsAvailable === true,
      observerFlushedBefore: flushedBefore === true,
      observerFlushedAfter: observerFlushedAfter === true,
      contentVersionBefore,
      contentVersionAfter,
      unknownMutationBefore: unknownBefore,
      unknownMutationAfter: unknownAfter,
      clearReturned: true,
      canvasResetObservationAvailable: resetObservationAvailable,
      targetCanvasId: operation.target?.canvasId ?? null,
    };
    segment.executedFullClearWitness = witness;
    trace.diagnostics.executedFullClearWitnessCount += 1;
    const nativeDiagnostics = window.__bookwalkerNativeCaptureDiagnostics;
    if (nativeDiagnostics) nativeDiagnostics.executedFullClearWitnessCount += 1;
    return true;
  };
  const updateExpectedTileCount = (segment, tile) => {
    if (segment.expectedTileCount !== null) return;
    const source = tile.source;
    const sourceRect = tile.sourceRect;
    const target = segment.target;
    if (!source || !sourceRect || !target
        || source.width !== target.width || source.height !== target.height
        || sourceRect.width <= 0 || sourceRect.height <= 0
        || sourceRect.width !== tile.destination.width
        || sourceRect.height !== tile.destination.height) return;
    if (target.width % sourceRect.width || target.height % sourceRect.height) return;
    segment.expectedTileCount =
      (target.width / sourceRect.width) * (target.height / sourceRect.height);
  };
  const retainCompletedMapping = mapping => {
    const trace = window.__bookwalkerTransformTrace;
    const tileCount = mapping.tileDraws.length;
    if (tileCount > MAX_COMPLETED_TILE_RECORDS) {
      trace.droppedCompletedMappingCount += 1;
      return;
    }
    let retainedTiles = trace.completedMappings.reduce(
      (total, item) => total + item.tileDraws.length, 0,
    );
    while (trace.completedMappings.length >= MAX_COMPLETED_MAPPINGS
        || retainedTiles + tileCount > MAX_COMPLETED_TILE_RECORDS) {
      const dropped = trace.completedMappings.shift();
      if (!dropped) break;
      retainedTiles -= dropped.tileDraws.length;
      trace.droppedCompletedMappingCount += 1;
    }
    trace.completedMappings.push(mapping);
  };
  const freezeCompletedMapping = (operation, sourceInfo, geometry, sourceObject) => {
    if (sourceInfo?.constructor !== 'HTMLCanvasElement' || !sourceInfo.canvasId) {
      return null;
    }
    const trace = window.__bookwalkerTransformTrace;
    const segment = trace?.activeSegments?.[sourceInfo.canvasId];
    if (!segment) return null;
    const mappingId = `mapping-${operation.index}`;
    let sourceSnapshotId = null;
    let sourceSnapshotError = null;
    if (segment.tileDraws.length > 0 && sourceObject?.constructor?.name === 'HTMLCanvasElement') {
      const snapshot = snapshotCanvasFull(sourceObject);
      sourceSnapshotId = snapshot.snapshotId;
      sourceSnapshotError = snapshot.error;
    }
    const mapping = {
      mappingId,
      rendererOperationIndex: operation.index,
      rendererTarget: operation.target,
      sourceCanvas: segment.tileTarget || segment.target,
      rendererSourceRect: geometry.sourceRect,
      rendererDestination: geometry.destination,
      rendererTransform: operation.transform,
      rendererAlpha: operation.globalAlpha,
      rendererComposite: operation.globalCompositeOperation,
      rendererFilter: operation.filter,
      segmentClearOperationIndex: segment.clearOperationIndex,
      segmentClearRectangle: segment.clearRectangle,
      segmentFirstTileOperationIndex: segment.tileDraws.length
        ? segment.tileDraws[0].operationIndex : null,
      segmentLastTileOperationIndex: segment.tileDraws.length
        ? segment.tileDraws[segment.tileDraws.length - 1].operationIndex : null,
      segmentTileCount: segment.tileDraws.length,
      segmentExpectedTileCount: segment.expectedTileCount,
      tileDraws: segment.tileDraws.map(tile => ({...tile, source: {...tile.source}, target: {...tile.target}})),
      sourceIds: [...segment.sourceIds],
      nonImageBitmapDraws: segment.nonImageBitmapDraws.map(draw => ({
        ...draw,
        source: draw.source ? {...draw.source} : null,
        target: draw.target ? {...draw.target} : null,
        sourceRect: draw.sourceRect ? {...draw.sourceRect} : null,
        destination: draw.destination ? {...draw.destination} : null,
        transform: draw.transform ? {...draw.transform} : null,
      })),
      unsafeOperationCount: segment.unsafeOperationCount,
      firstUnsafeOperationIndex: segment.firstUnsafeOperationIndex,
      unsafeOperationTypes: [...segment.unsafeOperationTypes],
      segmentOverflow: segment.overflow,
      segmentClearTarget: segment.clearTarget,
      segmentResetKind: segment.resetKind,
      segmentResetEpoch: segment.resetEpoch,
      segmentTraceEpoch: trace.traceEpoch,
      segmentDrawTarget: segment.tileTarget,
      segmentUnknownMutation: segment.unknownMutation,
      segmentResetObservationAvailable: segment.resetObservationAvailable,
      segmentMutationObserverAvailable: segment.mutationObserverAvailable,
      segmentMutationObserverTakeRecordsAvailable: segment.mutationObserverTakeRecordsAvailable,
      segmentExecutedFullClearWitness: segment.executedFullClearWitness || null,
      segmentExecutedFullClearWitnessRejection:
        segment.executedFullClearWitnessRejection || null,
      sourceSnapshotId,
      sourceSnapshotError,
      sourceSnapshotContentVersion: sourceObject?.constructor?.name === 'HTMLCanvasElement'
        ? contentVersion(sourceObject) : null,
    };
    retainCompletedMapping(mapping);
    return {mappingId, sourceCanvasId: sourceInfo.canvasId};
  };
  const recordDraw = (context, source, geometry) => {
    flushCanvasMutationObserver(context?.canvas);
    if (source?.constructor?.name === 'HTMLCanvasElement') {
      flushCanvasMutationObserver(source);
    }
    const operation = recordOperation('drawImage', context, {
      source: traceSourceInfo(source),
      sourceRect: geometry.sourceRect,
      destination: geometry.destination,
    });
    if (!operation) return null;
    const canvas = context.canvas;
    const sourceInfo = operation.source;
    const canvasId = getCanvasId(canvas);
    const segment = window.__bookwalkerTransformTrace?.activeSegments?.[canvasId];
    let tileRecord = null;
    let nonImageBitmapRecord = null;
    if (segment) {
      const safe = isSafeDraw(operation);
      if (sourceInfo?.constructor !== 'ImageBitmap') {
        markUnsafe(canvas, operation.index, 'non_image_bitmap_draw');
        if (segment.nonImageBitmapDraws.length < MAX_NON_IMAGE_BITMAP_DRAW_RECORDS) {
          nonImageBitmapRecord = {
            operationIndex: operation.index,
            traceEpoch: operation.traceEpoch,
            source: sourceInfo ? {...sourceInfo} : null,
            target: operation.target ? {...operation.target} : null,
            targetContentVersionBefore: operation.target?.contentVersion ?? null,
            targetContentVersionAfter: null,
            sourceRect: geometry.sourceRect ? {...geometry.sourceRect} : null,
            destination: geometry.destination ? {...geometry.destination} : null,
            transform: operation.transform ? {...operation.transform} : null,
            globalAlpha: operation.globalAlpha,
            globalCompositeOperation: operation.globalCompositeOperation,
            filter: operation.filter,
            imageSmoothingEnabled: typeof context.imageSmoothingEnabled === 'boolean'
              ? context.imageSmoothingEnabled : null,
            imageSmoothingQuality: typeof context.imageSmoothingQuality === 'string'
              ? context.imageSmoothingQuality : null,
          };
          segment.nonImageBitmapDraws.push(nonImageBitmapRecord);
        }
      } else if (!safe) {
        if (operation.transform && (
            operation.transform.a !== 1 || operation.transform.b !== 0
            || operation.transform.c !== 0 || operation.transform.d !== 1
            || operation.transform.e !== 0 || operation.transform.f !== 0)) {
          markUnsafe(canvas, operation.index, 'transform_change');
        }
        if (operation.globalAlpha !== 1 && operation.globalAlpha !== 1.0) {
          markUnsafe(canvas, operation.index, 'alpha');
        }
        if (operation.globalCompositeOperation !== 'source-over') {
          markUnsafe(canvas, operation.index, 'composite');
        }
        if (operation.filter !== 'none') markUnsafe(canvas, operation.index, 'filter');
      } else if (!geometry.sourceRect || !geometry.destination) {
        markUnsafe(canvas, operation.index, 'draw_geometry_unavailable');
      } else if (segment.tileDraws.length >= MAX_TILE_DRAWS_PER_SEGMENT) {
        segment.overflow = true;
      } else {
        const currentTarget = operation.target;
        if (!segment.tileTarget) {
          segment.tileTarget = currentTarget;
        } else if (
          segment.tileTarget.canvasId !== currentTarget.canvasId
          || segment.tileTarget.width !== currentTarget.width
          || segment.tileTarget.height !== currentTarget.height
          || segment.tileTarget.resetEpoch !== currentTarget.resetEpoch
        ) {
          markUnsafe(canvas, operation.index, 'target_canvas_dimension_change');
          segment.unknownMutation = true;
        }
        if (segment.unknownMutation) return;
        tileRecord = {
          operationIndex: operation.index,
          source: sourceInfo,
          target: operation.target,
          sourceContentVersion: sourceInfo?.contentVersion ?? null,
          targetContentVersionBefore: operation.target?.contentVersion ?? null,
          targetContentVersionAfter: null,
          sourceRect: geometry.sourceRect,
          destination: geometry.destination,
          transform: operation.transform,
          globalAlpha: operation.globalAlpha,
          globalCompositeOperation: operation.globalCompositeOperation,
          filter: operation.filter,
        };
        segment.tileDraws.push(tileRecord);
        if (!segment.sourceIds.includes(sourceInfo.sourceId)) {
          segment.sourceIds.push(sourceInfo.sourceId);
        }
        updateExpectedTileCount(segment, tileRecord);
      }
    }
    return {
      operation,
      completed: freezeCompletedMapping(operation, sourceInfo, geometry, source),
      tileRecord,
      nonImageBitmapRecord,
    };
  };
  const snapshotSourceCrop = (source, sourceRect) => {
    if (!sourceRect || sourceRect.width <= 0 || sourceRect.height <= 0) {
      return {snapshotId: null, error: 'invalid source rectangle'};
    }
    const target = document.createElement('canvas');
    window.__bookwalkerMarkInternalCanvas?.(target);
    target.width = Math.round(sourceRect.width);
    target.height = Math.round(sourceRect.height);
    const context = target.getContext('2d');
    if (!context) return {snapshotId: null, error: '2d context unavailable'};
    try {
      original.call(
        context,
        source,
        sourceRect.x, sourceRect.y, sourceRect.width, sourceRect.height,
        0, 0, sourceRect.width, sourceRect.height,
      );
      const snapshotId = String(nextSourceId++);
      window.__bookwalkerNativeSnapshots.set(snapshotId, target);
      while (window.__bookwalkerNativeSnapshots.size > 100) {
        const oldest = window.__bookwalkerNativeSnapshots.keys().next().value;
        window.__bookwalkerNativeSnapshots.delete(oldest);
      }
      return {snapshotId, error: null};
    } catch (error) {
      return {snapshotId: null, error: String(error)};
    }
  };
  const snapshotCanvasFull = source => {
    if (!source || source.constructor?.name !== 'HTMLCanvasElement') {
      return {snapshotId: null, error: 'full canvas snapshot requires HTMLCanvasElement'};
    }
    return snapshotSourceCrop(source, {
      x: 0, y: 0, width: source.width, height: source.height,
    });
  };
  const directRectangleIsFullFrame = (source, rectangle, destination, target) => {
    if (!source || !rectangle || !destination || !target) return false;
    const close = (left, right) => Math.abs(Number(left) - Number(right)) <= 1e-7;
    return close(rectangle.x, 0) && close(rectangle.y, 0)
      && close(rectangle.width, Number(source.width))
      && close(rectangle.height, Number(source.height))
      && close(destination.x, 0) && close(destination.y, 0)
      && close(destination.width, Number(target.width))
      && close(destination.height, Number(target.height));
  };
  const directExternalDrawIsNonIntersecting = (record, operation) => {
    if (!record || !operation || operation.operation !== 'drawImage') return false;
    const source = operation.source;
    const sourceRect = operation.sourceRect;
    const destination = operation.destination;
    const roi = record.destination;
    const transform = operation.transform;
    const finite = value => Number.isFinite(Number(value));
    const integerBoundary = value => finite(value)
      && Math.abs(Number(value) - Math.round(Number(value))) <= 1e-9;
    const integerSeparatingAxis = (start, size, roiStart, roiSize) => {
      if (![start, size, roiStart, roiSize].every(finite)) return false;
      const end = Number(start) + Number(size);
      const roiEnd = Number(roiStart) + Number(roiSize);
      if (end <= Number(roiStart)) {
        return integerBoundary(end) && integerBoundary(roiStart);
      }
      if (roiEnd <= Number(start)) {
        return integerBoundary(roiEnd) && integerBoundary(start);
      }
      return false;
    };
    if (!source || !sourceRect || !destination || !roi || !transform) return false;
    if (source.width === null || source.height === null
        || sourceRect.x < 0 || sourceRect.y < 0
        || sourceRect.width <= 0 || sourceRect.height <= 0
        || sourceRect.x + sourceRect.width > source.width
        || sourceRect.y + sourceRect.height > source.height) return false;
    if (![destination.x, destination.y, destination.width, destination.height,
      roi.x, roi.y, roi.width, roi.height].every(finite)
      || destination.width <= 0 || destination.height <= 0
      || roi.width <= 0 || roi.height <= 0) return false;
    if (transform.a !== 1 || transform.b !== 0 || transform.c !== 0
        || transform.d !== 1 || transform.e !== 0 || transform.f !== 0
        || operation.globalAlpha !== 1
        || operation.globalCompositeOperation !== 'source-over'
        || operation.filter !== 'none') return false;
    if (operation.shadowBlur !== 0 || operation.shadowOffsetX !== 0
        || operation.shadowOffsetY !== 0
        || !['rgba(0, 0, 0, 0)', 'transparent'].includes(operation.shadowColor)) {
      return false;
    }
    return integerSeparatingAxis(
      destination.x, destination.width, roi.x, roi.width,
    ) || integerSeparatingAxis(
      destination.y, destination.height, roi.y, roi.height,
    );
  };
  const directRecordMutation = (canvas, operationIndex, kind, operation = null) => {
    for (const record of window.__bookwalkerDirectOneHopRecords) {
      if (record.rendererTargetObject !== canvas) continue;
      if (operationIndex <= record.rendererOperationIndex) continue;
      if (kind !== 'unsupportedMutation' && !record.rendererMutation) {
        record.rendererMutation = kind;
        record.rendererMutationOperationIndex = operationIndex;
      }
      record.rendererLastMutation = kind;
      const safeSaveRestore = (kind === 'save' || kind === 'restore')
        && operation?.contextSafety?.knownNoClip === true
        && operation?.contextSafety?.saveStackKnown === true;
      const safeExternalDraw = kind === 'drawImage'
        && directExternalDrawIsNonIntersecting(record, operation);
      if (safeExternalDraw) {
        record.rendererNonIntersectingDraw = true;
      }
      if (['clip', 'transformChange', 'canvas_dimension_reset', 'unknownMutation',
        'clearRect', 'contextlost'].includes(kind)
        || (['save', 'restore'].includes(kind) && !safeSaveRestore)
        || (kind === 'drawImage' && !safeExternalDraw)) {
        if (!record.rendererFirstHardInvalid) {
          record.rendererFirstHardInvalid = {
            kind,
            operationIndex,
            source: operation?.source ? {...operation.source}
              : record.sourceInfo ? {...record.sourceInfo} : null,
            target: operation?.target ? {...operation.target}
              : record.targetInfo ? {...record.targetInfo} : null,
            sourceRect: operation?.sourceRect ? {...operation.sourceRect}
              : record.sourceRect ? {...record.sourceRect} : null,
            destination: operation?.destination ? {...operation.destination}
              : operation?.relevantRectangle ? {...operation.relevantRectangle}
              : record.destination ? {...record.destination} : null,
            transform: operation?.transform ? {...operation.transform}
              : record.transform ? {...record.transform} : null,
            globalAlpha: operation?.globalAlpha ?? record.globalAlpha,
            globalCompositeOperation: operation?.globalCompositeOperation
              ?? record.globalCompositeOperation,
            filter: operation?.filter ?? record.filter,
            method: operation?.method || null,
            sourceContentVersion: record.sourceContentVersion,
            targetContentVersionBefore: record.targetContentVersionBefore,
          };
        }
        record.rendererUnsafeMutation = kind;
        record.rendererInvalidated = true;
        record.rendererInvalidationOperationIndex = operationIndex;
      }
    }
  };
  const markContextSafetyUnknown = context => {
    if (!context) return;
    const state = ensureContextState(context);
    if (state) {
      state.knownNoClip = false;
      state.saveStack = [];
    }
    contextSafetyUnknown.set(context, true);
  };
  const directSnapshot = (source, rectangle) => {
    const snapshot = snapshotSourceCrop(source, rectangle);
    if (snapshot.snapshotId) {
      const id = String(snapshot.snapshotId);
      const canvas = window.__bookwalkerNativeSnapshots.get(id);
      if (canvas) {
        window.__bookwalkerNativeSnapshots.delete(id);
        window.__bookwalkerDirectOneHopSnapshots.set(id, canvas);
      }
    }
    return snapshot;
  };
  const directFullSnapshot = source => {
    if (!source || source.constructor?.name !== 'HTMLCanvasElement') {
      return {snapshotId: null, error: 'full canvas snapshot requires HTMLCanvasElement'};
    }
    return directSnapshot(source, {
      x: 0, y: 0, width: source.width, height: source.height,
    });
  };
  const directSnapshotCanvas = id => (
    window.__bookwalkerDirectOneHopSnapshots.get(String(id))
      || window.__bookwalkerNativeSnapshots.get(String(id))
  );
  const directDropRecordSnapshots = record => {
    for (const id of [record?.sourceSnapshotId, record?.intermediateSnapshotId,
      record?.targetSnapshotId]) {
      if (id !== null && id !== undefined) {
        window.__bookwalkerDirectOneHopSnapshots.delete(String(id));
      }
    }
  };
  const directEvictChain = record => {
    if (!record) return;
    const sourceObject = record.kind === 'source_to_canvas'
      ? record.targetObject : record.sourceObject;
    const chain = window.__bookwalkerDirectOneHopRecords.filter(candidate => (
      candidate && candidate.token === record.token
      && (candidate === record
        || (candidate.kind === 'source_to_canvas' && candidate.targetObject === sourceObject)
        || (candidate.kind === 'canvas_to_renderer' && candidate.sourceObject === sourceObject))
    ));
    if (!chain.length) return;
    const chainSet = new Set(chain);
    for (const item of chain) {
      directDropRecordSnapshots(item);
      directOneHopSnapshotBytes = Math.max(
        0, directOneHopSnapshotBytes - Number(item.snapshotBytes || 0),
      );
    }
    window.__bookwalkerDirectOneHopRecords =
      window.__bookwalkerDirectOneHopRecords.filter(item => !chainSet.has(item));
  };
  const directPrepareSnapshotBudget = (requiredBytes, targetObject) => {
    while (directOneHopSnapshotBytes + requiredBytes > 32 * 1024 * 1024) {
      const oldest = window.__bookwalkerDirectOneHopRecords
        .slice()
        .sort((left, right) => Number(left.operationIndex || 0) - Number(right.operationIndex || 0))[0];
      if (!oldest) break;
      const sameTargetChain = window.__bookwalkerDirectOneHopRecords.find(item => (
        item && item.kind === 'source_to_canvas' && item.targetObject === targetObject
      ));
      directEvictChain(sameTargetChain || oldest);
    }
    return directOneHopSnapshotBytes + requiredBytes <= 32 * 1024 * 1024;
  };
  const directTrimRecords = () => {
    while (window.__bookwalkerDirectOneHopRecords.length > 4) {
      const oldest = window.__bookwalkerDirectOneHopRecords
        .slice()
        .sort((left, right) => Number(left.operationIndex || 0) - Number(right.operationIndex || 0))[0];
      directEvictChain(oldest);
    }
  };
  const directBeforeDraw = (context, source, geometry, operation) => {
    if (!window.__bookwalkerNativeCaptureEnabled
        || window.__bookwalkerDirectOriginalEnabled !== true
        || !source || !operation) return null;
    const target = context?.canvas;
    if (!target || !geometry?.sourceRect || !geometry?.destination) return null;
    const safety = ensureContextState(context);
    if (!safety || safety.knownNoClip !== true
        || contextSafetyUnknown.get(context) === true) return null;
    const sourceName = source.constructor?.name || null;
    const targetName = target.constructor?.name || null;
    const isCopy = sourceName === 'ImageBitmap'
      && directRectangleIsFullFrame(source, geometry.sourceRect, geometry.destination, target)
      && Number(target.width) <= 1000 && Number(target.height) > 500;
    const isRenderer = sourceName === 'HTMLCanvasElement'
      && targetName === 'HTMLCanvasElement'
      && Number(source.width) > 0 && Number(source.height) > 0
      && Number(target.width) > 1000 && Number(target.height) > 500
      && Math.abs(Number(geometry.sourceRect.x)) <= 1e-7
      && Math.abs(Number(geometry.sourceRect.y)) <= 1e-7
      && Number(geometry.sourceRect.width) > 0
      && Number(geometry.sourceRect.height) > 0
      && Number(source.width) - Number(geometry.sourceRect.width) >= 0
      && Number(source.width) - Number(geometry.sourceRect.width) <= 0.5
      && Number(source.height) - Number(geometry.sourceRect.height) >= 0
      && Number(source.height) - Number(geometry.sourceRect.height) <= 0.5
      && Number(geometry.sourceRect.x) + Number(geometry.sourceRect.width) <= Number(source.width) + 0.5
      && Number(geometry.sourceRect.y) + Number(geometry.sourceRect.height) <= Number(source.height) + 0.5;
    const hasOriginCopy = window.__bookwalkerDirectOneHopRecords.some(candidate => (
      candidate && candidate.kind === 'source_to_canvas'
      && candidate.targetObject === source
      && candidate.token === String(window.__bookwalkerDirectOneHopToken)
    ));
    if (isRenderer && !hasOriginCopy) return null;
    if (!isCopy && !isRenderer) return null;
    const snapshotBytes = isCopy
      ? Number(source.width) * Number(source.height) * 4
        + Number(target.width) * Number(target.height) * 4
      : Number(source.width) * Number(source.height) * 4
        + Math.ceil(Number(geometry.destination.width))
          * Math.ceil(Number(geometry.destination.height)) * 4;
    if (!Number.isFinite(snapshotBytes) || snapshotBytes <= 0
        || !directPrepareSnapshotBudget(snapshotBytes, isCopy ? target : source)) return null;
    const sourceSnapshot = isCopy
      ? directSnapshot(source, geometry.sourceRect)
      : directFullSnapshot(source);
    return {
      kind: isCopy ? 'source_to_canvas' : 'canvas_to_renderer',
      token: String(window.__bookwalkerDirectOneHopToken),
      frameToken: String(window.__bookwalkerDirectOneHopToken),
      sourceObject: source,
      targetObject: target,
      sourceId: getSourceId(source),
      sourceInfo: traceSourceInfo(source),
      targetInfo: targetInfo(target),
      sourceRect: {...geometry.sourceRect},
      destination: {...geometry.destination},
      transform: operation.transform,
      globalAlpha: operation.globalAlpha,
      globalCompositeOperation: operation.globalCompositeOperation,
      filter: operation.filter,
      imageSmoothingEnabled: typeof context.imageSmoothingEnabled === 'boolean'
        ? context.imageSmoothingEnabled : null,
      imageSmoothingQuality: typeof context.imageSmoothingQuality === 'string'
        ? context.imageSmoothingQuality : null,
      operationIndex: operation.index,
      sourceContentVersion: sourceName === 'HTMLCanvasElement' ? contentVersion(source) : null,
      targetContentVersionBefore: contentVersion(target),
      geometryVersion: directGeometryVersionFor(target),
      sourceSnapshotId: sourceSnapshot.snapshotId,
      sourceSnapshotError: sourceSnapshot.error,
      rendererMutation: null,
      rendererMutationOperationIndex: null,
      rendererUnsafeMutation: null,
      rendererLastMutation: null,
      rendererInvalidated: false,
      rendererInvalidationOperationIndex: null,
      rendererFirstHardInvalid: null,
      rendererNonIntersectingDraw: false,
      snapshotBytes,
    };
  };
  const directAfterDraw = (record, context) => {
    if (!record) return;
    if (directOneHopSnapshotBytes + record.snapshotBytes > 32 * 1024 * 1024) {
      directDropRecordSnapshots(record);
      return;
    }
    const target = context?.canvas;
    const targetVersion = advanceContentVersion(target);
    record.targetContentVersionAfter = targetVersion;
    record.operationOrder = [record.operationIndex];
    if (record.kind === 'source_to_canvas') {
      const full = directFullSnapshot(target);
      record.intermediateSnapshotId = full.snapshotId;
      record.intermediateSnapshotError = full.error;
      record.targetSnapshotId = full.snapshotId;
    } else {
      const roi = directSnapshot(target, record.destination);
      record.targetSnapshotId = roi.snapshotId;
      record.targetSnapshotError = roi.error;
      record.rendererTargetObject = target;
      record.rendererOperationIndex = record.operationIndex;
    }
    window.__bookwalkerDirectOneHopRecords.push(record);
    directOneHopSnapshotBytes += record.snapshotBytes;
    directTrimRecords();
  };
  window.__bookwalkerMaterializeDirectOneHop = currentCanvas => {
    flushCanvasMutationObserver(currentCanvas);
    const materialize = canvas => {
      if (!canvas) return {dataUrl: null, error: 'snapshot canvas unavailable'};
      try { return {dataUrl: canvas.toDataURL('image/png'), error: null}; }
      catch (error) { return {dataUrl: null, error: String(error)}; }
    };
    const cropCurrent = (canvas, rectangle) => {
      if (!canvas || !rectangle) return {dataUrl: null, error: 'current canvas unavailable'};
      const snapshot = snapshotSourceCrop(canvas, rectangle);
      if (!snapshot.snapshotId) return {dataUrl: null, error: snapshot.error};
      const result = materialize(window.__bookwalkerNativeSnapshots.get(String(snapshot.snapshotId)));
      window.__bookwalkerNativeSnapshots.delete(String(snapshot.snapshotId));
      return result;
    };
    const result = [];
    for (const record of window.__bookwalkerDirectOneHopRecords) {
      if (!record || record.kind !== 'canvas_to_renderer') continue;
      const copy = window.__bookwalkerDirectOneHopRecords.find(candidate => (
        candidate && candidate.kind === 'source_to_canvas'
        && candidate.targetObject === record.sourceObject
        && candidate.token === record.token
        && candidate.targetContentVersionAfter === record.sourceContentVersion
        && candidate.operationIndex < record.operationIndex
      ));
      const sourceSnapshot = copy
        ? materialize(directSnapshotCanvas(copy.sourceSnapshotId)) : null;
      const intermediate = copy
        ? materialize(directSnapshotCanvas(copy.intermediateSnapshotId)) : null;
      const sourceB = materialize(
        directSnapshotCanvas(record.sourceSnapshotId),
      );
      const renderer = materialize(directSnapshotCanvas(record.targetSnapshotId));
      const current = record.rendererTargetObject === currentCanvas
        ? cropCurrent(currentCanvas, record.destination) : {dataUrl: null, error: 'current canvas identity mismatch'};
      result.push({
        token: record.token,
        frameToken: record.frameToken,
        currentToken: String(window.__bookwalkerDirectOneHopToken),
        pageUrl: String(window.location.href),
        pageCounter: document.querySelector('#pageSliderCounter')?.textContent || null,
        currentConnected: Boolean(currentCanvas?.isConnected && document.contains(currentCanvas)),
        copy: copy ? {
          sourceId: copy.sourceId,
          sourceInfo: copy.sourceInfo,
          targetInfo: copy.targetInfo,
          sourceRect: copy.sourceRect,
          destination: copy.destination,
          transform: copy.transform,
          globalAlpha: copy.globalAlpha,
          globalCompositeOperation: copy.globalCompositeOperation,
          filter: copy.filter,
          imageSmoothingEnabled: copy.imageSmoothingEnabled,
          imageSmoothingQuality: copy.imageSmoothingQuality,
          operationIndex: copy.operationIndex,
          targetContentVersionAfter: copy.targetContentVersionAfter,
          sourceSnapshot: sourceSnapshot?.dataUrl || null,
          sourceSnapshotError: sourceSnapshot?.error || copy.sourceSnapshotError,
          intermediate: intermediate?.dataUrl || null,
          intermediateError: intermediate?.error || copy.intermediateSnapshotError,
        } : null,
        renderer: {
          sourceId: record.sourceId,
          sourceInfo: record.sourceInfo,
          targetInfo: record.targetInfo,
          sourceRect: record.sourceRect,
          destination: record.destination,
          transform: record.transform,
          globalAlpha: record.globalAlpha,
          globalCompositeOperation: record.globalCompositeOperation,
          filter: record.filter,
          imageSmoothingEnabled: record.imageSmoothingEnabled,
          imageSmoothingQuality: record.imageSmoothingQuality,
          operationIndex: record.operationIndex,
          sourceContentVersion: record.sourceContentVersion,
          geometryVersion: record.geometryVersion,
          currentGeometryVersion: directGeometryVersionFor(record.rendererTargetObject),
          geometryHistoryIncomplete: directGeometryHistoryIncompleteFor(
            record.rendererTargetObject
          ),
          targetContentVersionAfter: record.targetContentVersionAfter,
          targetSnapshot: renderer?.dataUrl || null,
          targetSnapshotError: renderer?.error || record.targetSnapshotError,
          mutation: record.rendererMutation,
          mutationOperationIndex: record.rendererMutationOperationIndex,
          unsafeMutation: record.rendererUnsafeMutation,
          lastMutation: record.rendererLastMutation,
          invalidated: record.rendererInvalidated,
          invalidationOperationIndex: record.rendererInvalidationOperationIndex,
          firstHardInvalid: record.rendererFirstHardInvalid,
          nonIntersectingDraw: record.rendererNonIntersectingDraw,
          sameCurrentObject: record.rendererTargetObject === currentCanvas,
          currentContentVersion: record.rendererTargetObject === currentCanvas
            ? contentVersion(currentCanvas) : null,
          current: current.dataUrl,
          currentError: current.error,
          sourceB: sourceB.dataUrl,
          sourceBError: sourceB.error || record.sourceSnapshotError,
        },
      });
    }
    return result;
  };
  window.__bookwalkerDirectOneHopCurrentState = currentCanvas => {
    flushCanvasMutationObserver(currentCanvas);
    return {
      token: String(window.__bookwalkerDirectOneHopToken || ''),
      pageUrl: String(window.location.href),
      pageCounter: document.querySelector('#pageSliderCounter')?.textContent || null,
      connected: Boolean(currentCanvas?.isConnected && document.contains(currentCanvas)),
      activeOperationIndex: window.__bookwalkerDirectOneHopRecords
        .filter(record => record && record.rendererTargetObject === currentCanvas)
        .reduce((latest, record) => Math.max(latest, Number(record.rendererOperationIndex || 0)), 0),
      geometryVersion: directGeometryVersionFor(currentCanvas),
      geometryHistoryIncomplete: directGeometryHistoryIncompleteFor(currentCanvas),
      records: window.__bookwalkerDirectOneHopRecords
        .filter(record => record && record.rendererTargetObject === currentCanvas)
        .map(record => ({
          operationIndex: record.rendererOperationIndex,
          mutation: record.rendererMutation,
          unsafeMutation: record.rendererUnsafeMutation,
          lastMutation: record.rendererLastMutation,
          invalidated: record.rendererInvalidated,
          firstHardInvalid: record.rendererFirstHardInvalid,
          nonIntersectingDraw: record.rendererNonIntersectingDraw,
          targetContentVersionAfter: record.targetContentVersionAfter,
          currentContentVersion: contentVersion(currentCanvas),
        })),
    };
  };
  window.__bookwalkerDirectOneHopGeometryState = currentCanvas => ({
    observerFlushed: flushCanvasMutationObserver(currentCanvas),
    observerAvailable: canvasMutationObserverStates.get(currentCanvas)?.available === true,
    observerTakeRecordsAvailable:
      canvasMutationObserverStates.get(currentCanvas)?.takeRecordsAvailable === true,
    token: String(window.__bookwalkerDirectOneHopToken || ''),
    traceEpoch: Number(window.__bookwalkerTransformTrace?.traceEpoch || 0),
    geometryVersion: directGeometryVersionFor(currentCanvas),
    contentVersion: contentVersion(currentCanvas),
    geometryHistoryIncomplete: directGeometryHistoryIncompleteFor(currentCanvas),
    canvasId: currentCanvas ? getCanvasId(currentCanvas) : null,
    connected: Boolean(currentCanvas?.isConnected && document.contains(currentCanvas)),
    unknownMutation: currentCanvas ? canvasUnknownMutations.has(currentCanvas) : null,
    resetEpoch: currentCanvas ? Number(canvasResetEpochs.get(currentCanvas) || 0) : null,
    width: currentCanvas ? Number(currentCanvas.width) : null,
    height: currentCanvas ? Number(currentCanvas.height) : null,
    bookIdentity: (() => {
      try { return new URL(window.location.href).searchParams.get('cid') || null; }
      catch (error) { return null; }
    })(),
    geometryHistoryLimit: DIRECT_GEOMETRY_LEDGER_LIMIT,
    geometryLedgerLength: window.__bookwalkerDrawCalls.length,
    geometryHistoryEvictions: directGeometryHistoryEvictions,
  });
  // One raw anchor builder is shared by the diagnostic capture-before and
  // capture-after checks.  Keeping the object identity and field shape here
  // avoids comparing a legacy summary with the stricter final anchor.
  window.__bookwalkerP4BCurrentAnchor = (element, expectedOperationIndex) => {
    const traceId = element?.getAttribute('data-bookwalker-trace-id') || null;
    const actualCanvasId = element ? String(getCanvasId(element) || '') : null;
    const calls = (window.__bookwalkerNativeDrawCalls || [])
      .filter(call => call?.canvasId === traceId);
    const selected = calls.find(call => (
      (call?.operation?.index ?? call?.traceOperationIndex ?? null)
      === expectedOperationIndex
    )) || null;
    const geometry = window.__bookwalkerDirectOneHopGeometryState?.(element) || null;
    let bookIdentity = null;
    try { bookIdentity = new URL(window.location.href).searchParams.get('cid') || null; }
    catch (error) {}
    return {
      traceId,
      actualCanvasId,
      connected: Boolean(element?.isConnected && document.contains(element)),
      bookIdentity,
      counter: document.querySelector('#pageSliderCounter')?.textContent || null,
      nativeCallCount: calls.length,
      operationIndices: calls.map(call =>
        call?.operation?.index ?? call?.traceOperationIndex ?? null),
      geometryToken: geometry?.token ?? null,
      traceEpoch: geometry?.traceEpoch ?? null,
      geometryVersion: geometry?.geometryVersion ?? null,
      geometryHistoryIncomplete: geometry?.geometryHistoryIncomplete ?? null,
      observerFlushed: geometry?.observerFlushed ?? null,
      observerAvailable: geometry?.observerAvailable ?? null,
      observerTakeRecordsAvailable: geometry?.observerTakeRecordsAvailable ?? null,
      unknownMutation: geometry?.unknownMutation ?? null,
      resetEpoch: geometry?.resetEpoch ?? null,
      canvasWidth: geometry?.width ?? null,
      canvasHeight: geometry?.height ?? null,
      targetContentVersion: geometry?.contentVersion ?? null,
      selected: selected ? {
        canvasId: selected.canvasId ?? null,
        operationIndex: selected?.operation?.index ?? selected?.traceOperationIndex ?? null,
        sourceId: selected.sourceId ?? null,
        sourceCanvasId: selected.sourceCanvasId ?? null,
        traceEpoch: selected?.operation?.traceEpoch ?? selected?.traceEpoch ?? null,
        snapshotId: selected.snapshotId ?? null,
        sourceContentVersion: selected.sourceContentVersion ?? null,
        fullSourceSnapshotId: selected.fullSourceSnapshotId ?? null,
        targetSnapshotId: selected.targetSnapshotId ?? null,
        targetContentVersionAfter: selected.targetContentVersionAfter ?? null,
        sourceRect: selected.sourceRect ?? null,
        destination: selected.destination ?? null,
      } : null,
    };
  };
  const materializeNativeCrop = ({sourceId, snapshotId, sourceConstructor, sourceRect}) => {
    if (sourceConstructor === 'HTMLCanvasElement') {
      const snapshot = window.__bookwalkerNativeSnapshots.get(String(snapshotId));
      if (!snapshot) return {dataUrl: null, error: 'native canvas snapshot unavailable'};
      try {
        return {dataUrl: snapshot.toDataURL('image/png'), error: null};
      } catch (error) {
        return {dataUrl: null, error: String(error)};
      }
    }
    const source = window.__bookwalkerNativeSourceObjects.get(String(sourceId));
    if (!source || !sourceRect || sourceRect.width <= 0 || sourceRect.height <= 0) {
      return {dataUrl: null, error: 'native source crop unavailable'};
    }
    const target = document.createElement('canvas');
    window.__bookwalkerMarkInternalCanvas?.(target);
    target.width = Math.round(sourceRect.width);
    target.height = Math.round(sourceRect.height);
    const context = target.getContext('2d');
    if (!context) return {dataUrl: null, error: '2d context unavailable'};
    try {
      original.call(
        context,
        source,
        sourceRect.x, sourceRect.y, sourceRect.width, sourceRect.height,
        0, 0, sourceRect.width, sourceRect.height,
      );
      return {dataUrl: target.toDataURL('image/png'), error: null};
    } catch (error) {
      return {dataUrl: null, error: String(error)};
    }
  };
  window.__bookwalkerMaterializeNativeSourceCrop = materializeNativeCrop;
  CanvasRenderingContext2D.prototype.drawImage = function(...args) {
    if (internalCanvases.has(this.canvas)) return original.apply(this, args);
    let recorded = null;
    let nativeCall = null;
    let directRecord = null;
    try {
      const values = args.slice(1).map(value => Number(value));
      const geometry = sourceRectAndDestination(args[0], values);
      recorded = recordDraw(this, args[0], geometry);
      if (this.canvas && this.canvas.width > 1000 && this.canvas.height > 500
          && geometry.destination
          && geometry.destination.width >= 100
          && geometry.destination.height >= 100) {
        directGeometryVersions.set(
          this.canvas, directGeometryVersionFor(this.canvas) + 1,
        );
      }
      directRecord = directBeforeDraw(this, args[0], geometry, recorded?.operation);
      const canvas = this.canvas;
      if (canvas && canvas.width > 1000 && canvas.height > 500) {
        const destination = values.length >= 8
          ? values.slice(4, 8)
          : geometry.destination
            ? [
                geometry.destination.x, geometry.destination.y,
                geometry.destination.width, geometry.destination.height,
              ]
            : null;
        if (destination && !definitelySmallNativeDestination(geometry.destination)) {
          window.__bookwalkerDrawCalls.push({
            canvasId: getCanvasId(canvas),
            canvasWidth: canvas.width,
            canvasHeight: canvas.height,
            destination,
            operationIndex: recorded?.operation?.index || null,
            traceEpoch: window.__bookwalkerTransformTrace?.traceEpoch || null,
            resetEpoch: canvasResetEpochs.get(canvas) || 0,
          });
          const geometryLedgerLimit = window.__bookwalkerDirectOriginalEnabled === true
            ? DIRECT_GEOMETRY_LEDGER_LIMIT : 500;
          if (window.__bookwalkerDrawCalls.length > geometryLedgerLimit) {
            const evicted = window.__bookwalkerDrawCalls.shift();
            if (window.__bookwalkerDirectOriginalEnabled === true) {
              directGeometryHistoryEvictions += 1;
              if (evicted?.canvasId) directGeometryEvictedCanvasIds.add(evicted.canvasId);
            }
          }
        } else if (destination) {
          const diagnostics = window.__bookwalkerNativeCaptureDiagnostics;
          if (diagnostics) diagnostics.geometrySmallCallsDropped += 1;
        }
        if (window.__bookwalkerNativeCaptureEnabled && args[0] && geometry.destination) {
          const diagnostics = window.__bookwalkerNativeCaptureDiagnostics;
          if (diagnostics) diagnostics.nativeCallsSeen += 1;
          if (definitelySmallNativeDestination(geometry.destination)) {
            if (diagnostics) diagnostics.definitelySmallCallsDropped += 1;
          } else {
            const source = args[0];
            const sourceInfo = recorded?.operation?.source || traceSourceInfo(source);
            nativeCall = {
              timestamp: performance.now(),
              canvasId: getCanvasId(canvas),
              canvasWidth: canvas.width,
              canvasHeight: canvas.height,
              sourceId: sourceInfo?.sourceId || getSourceId(source),
              source: sourceInfo,
              _bookwalkerSourceObject: source,
              sourceCanvasId: sourceInfo?.canvasId || null,
              sourceContentVersion: sourceInfo?.contentVersion ?? null,
              traceEpoch: window.__bookwalkerTransformTrace?.traceEpoch || null,
              targetResetEpoch: canvasResetEpochs.get(canvas) || 0,
              sourceRect: geometry.sourceRect,
              destination: geometry.destination,
              argumentForm: values.length + 1,
              traceOperationIndex: recorded?.operation?.index || null,
              mappingId: recorded?.completed?.mappingId || null,
              transform: recorded?.operation?.transform || readTransform(this),
              globalAlpha: this.globalAlpha,
              globalCompositeOperation: this.globalCompositeOperation,
              filter: this.filter,
              imageSmoothingEnabled: typeof this.imageSmoothingEnabled === 'boolean'
                ? this.imageSmoothingEnabled : null,
              imageSmoothingQuality: typeof this.imageSmoothingQuality === 'string'
                ? this.imageSmoothingQuality : null,
            };
            if (source?.constructor?.name === 'HTMLCanvasElement') {
              const snapshot = snapshotSourceCrop(source, geometry.sourceRect);
              nativeCall.snapshotId = snapshot.snapshotId;
              nativeCall.snapshotError = snapshot.error;
            }
            nativeCall._bookwalkerPendingTargetSnapshot = true;
            nativeCall._bookwalkerPendingFullSourceSnapshot = source?.constructor?.name === 'HTMLCanvasElement';
          }
        }
      }
    } catch (error) {}
    const result = original.apply(this, args);
    if (directRecord) {
      try { directAfterDraw(directRecord, this); } catch (error) {}
    } else {
      const targetContentVersionAfter = advanceContentVersion(this.canvas);
      if (recorded?.operation?.index !== null
          && recorded?.operation?.index !== undefined) {
        const activeTile = recorded?.tileRecord;
        if (activeTile) activeTile.targetContentVersionAfter = targetContentVersionAfter;
        const activeNonImage = recorded?.nonImageBitmapRecord;
        if (activeNonImage) activeNonImage.targetContentVersionAfter = targetContentVersionAfter;
      }
    }
    if (nativeCall) {
      try {
        if (nativeCall._bookwalkerPendingFullSourceSnapshot) {
          const full = snapshotCanvasFull(nativeCall._bookwalkerSourceObject);
          nativeCall.fullSourceSnapshotId = full.snapshotId;
          nativeCall.fullSourceSnapshotError = full.error;
        }
        if (nativeCall._bookwalkerPendingFullSourceSnapshot) {
          const targetSnapshot = snapshotSourceCrop(this.canvas, nativeCall.destination);
          nativeCall.targetSnapshotId = targetSnapshot.snapshotId;
          nativeCall.targetSnapshotError = targetSnapshot.error;
        }
      } catch (error) {
        nativeCall.targetSnapshotId = null;
        nativeCall.targetSnapshotError = String(error);
      }
      nativeCall.targetContentVersionAfter = contentVersion(this.canvas);
      delete nativeCall._bookwalkerPendingTargetSnapshot;
      delete nativeCall._bookwalkerPendingFullSourceSnapshot;
      delete nativeCall._bookwalkerSourceObject;
      window.__bookwalkerNativeDrawCalls.push(nativeCall);
      const diagnostics = window.__bookwalkerNativeCaptureDiagnostics;
      if (diagnostics) diagnostics.nativeCallsAdmitted += 1;
      if (window.__bookwalkerNativeDrawCalls.length > 100) {
        window.__bookwalkerNativeDrawCalls.shift();
        if (diagnostics) diagnostics.nativeCallsEvicted += 1;
      }
      if (diagnostics) {
        diagnostics.nativeCallsRetained = window.__bookwalkerNativeDrawCalls.length;
      }
    }
    return result;
  };
  const rectangleDetails = args => {
    const values = args.slice(0, 4).map(value => Number(value));
    return {
      arguments: values,
      relevantRectangle: values.length === 4
        ? {x: values[0], y: values[1], width: values[2], height: values[3]}
        : null,
    };
  };
  const processCanvasMutationRecords = (canvas, records) => {
    for (const record of records) {
      if (record.type !== 'attributes' || (record.attributeName !== 'width' && record.attributeName !== 'height')) continue;
      const queue = knownAttributeMutations.get(canvas) || [];
      const current = canvas.getAttribute(record.attributeName);
      const matchIndex = queue.findIndex(item => (
        item.attributeName === record.attributeName
        && item.oldValue === record.oldValue
        && (item.newValue === null || item.newValue === current)
      ));
      if (matchIndex >= 0) {
        queue.splice(matchIndex, 1);
        if (queue.length) knownAttributeMutations.set(canvas, queue);
        else knownAttributeMutations.delete(canvas);
        continue;
      }
      canvasUnknownMutations.add(canvas);
      const trace = window.__bookwalkerTransformTrace;
      if (trace?.diagnostics) trace.diagnostics.unknownCanvasMutationCount += 1;
      directRecordMutation(canvas, Number(trace?.nextOperationIndex || 0) + 1, 'unknownMutation');
      const active = trace?.activeSegments?.[getCanvasId(canvas)];
      if (active) active.unknownMutation = true;
    }
  };
  const observeCanvasMutations = canvas => {
    if (!canvas) return;
    if (canvasMutationObserverStates.has(canvas)) {
      return canvasMutationObserverStates.get(canvas);
    }
    const state = {
      available: false,
      takeRecordsAvailable: false,
    };
    canvasMutationObserverStates.set(canvas, state);
    if (typeof MutationObserver !== 'function') return state;
    try {
      const observer = new MutationObserver(records => processCanvasMutationRecords(canvas, records));
      observer.observe(canvas, {attributes: true, attributeOldValue: true, attributeFilter: ['width', 'height']});
      canvasMutationObservers.set(canvas, observer);
      state.available = true;
      state.takeRecordsAvailable = typeof observer.takeRecords === 'function';
    } catch (error) {}
    return state;
  };
  const flushCanvasMutationObserver = canvas => {
    const observer = canvasMutationObservers.get(canvas);
    if (!observer || typeof observer.takeRecords !== 'function') return false;
    processCanvasMutationRecords(canvas, observer.takeRecords());
    return true;
  };
  const queueKnownAttributeMutation = (canvas, attributeName, oldValue, newValue) => {
    const queue = knownAttributeMutations.get(canvas) || [];
    const expected = {attributeName, oldValue, newValue};
    queue.push(expected);
    while (queue.length > 8) queue.shift();
    knownAttributeMutations.set(canvas, queue);
    setTimeout(() => {
      const current = knownAttributeMutations.get(canvas);
      if (current === queue) knownAttributeMutations.delete(canvas);
    }, 0);
    return expected;
  };
  const installCanvasDimensionResetTrace = property => {
    const prototype = HTMLCanvasElement.prototype;
    const descriptor = Object.getOwnPropertyDescriptor(prototype, property);
    if (!descriptor || typeof descriptor.get !== 'function'
        || typeof descriptor.set !== 'function' || !descriptor.configurable) {
      return false;
    }
    try {
      Object.defineProperty(prototype, property, {
        configurable: descriptor.configurable,
        enumerable: descriptor.enumerable,
        get: descriptor.get,
        set(value) {
          const canvas = this;
          if (internalCanvases.has(canvas)) return descriptor.set.call(canvas, value);
          const trace = window.__bookwalkerTransformTrace;
          const before = {
            width: Number(canvas.width), height: Number(canvas.height),
          };
          const oldAttributeValue = canvas.getAttribute(property);
          const shouldObserve = Boolean(
            trace && window.__bookwalkerCaptureMode === 'native',
          );
          const observerState = shouldObserve ? observeCanvasMutations(canvas) : null;
          const expectedMutation = shouldObserve
            ? queueKnownAttributeMutation(canvas, property, oldAttributeValue, null)
            : null;
          let result;
          try {
            result = descriptor.set.call(canvas, value);
          } catch (error) {
            const queue = knownAttributeMutations.get(canvas);
            if (queue && expectedMutation) {
              const index = queue.indexOf(expectedMutation);
              if (index >= 0) queue.splice(index, 1);
            }
            if (trace?.diagnostics) trace.diagnostics.canvasResetFailureCount += 1;
            const active = trace?.activeSegments?.[getCanvasId(canvas)];
            if (active) active.unknownMutation = true;
            throw error;
          }
          markCanvasContextsKnownFresh(canvas);
          if (!shouldObserve) return result;
          flushCanvasMutationObserver(canvas);
          const pendingQueue = knownAttributeMutations.get(canvas);
          if (pendingQueue) {
            const index = expectedMutation ? pendingQueue.indexOf(expectedMutation) : -1;
            if (index >= 0) pendingQueue.splice(index, 1);
            if (!pendingQueue.length) knownAttributeMutations.delete(canvas);
          }
          const after = {
            width: Number(canvas.width), height: Number(canvas.height),
          };
          canvasUnknownMutations.delete(canvas);
          const canvasId = getCanvasId(canvas);
          const operationIndex = ++trace.nextOperationIndex;
          trace.diagnostics.observedOperationCount = operationIndex;
          directRecordMutation(canvas, operationIndex, 'canvas_dimension_reset');
          const resetEpoch = (canvasResetEpochs.get(canvas) || 0) + 1;
          canvasResetEpochs.set(canvas, resetEpoch);
          const active = trace.activeSegments?.[canvasId];
          if (active) {
            active.unknownMutation = true;
            active.mutationObserverAvailable = observerState?.available === true;
            active.mutationObserverTakeRecordsAvailable = observerState?.takeRecordsAvailable === true;
          }
          newSegment(
            canvas,
            operationIndex,
            {x: 0, y: 0, width: after.width, height: after.height},
            'canvas_dimension_reset',
            resetEpoch,
          );
          const resetSegment = trace.activeSegments?.[canvasId];
          if (resetSegment) {
            resetSegment.mutationObserverAvailable = observerState?.available === true;
            resetSegment.mutationObserverTakeRecordsAvailable = observerState?.takeRecordsAvailable === true;
            resetSegment.resetObservationAvailable = Boolean(
              window.__bookwalkerCanvasResetObservationAvailable === true
              && resetSegment.mutationObserverAvailable
              && resetSegment.mutationObserverTakeRecordsAvailable
            );
          }
          advanceContentVersion(canvas);
          return result;
        },
      });
      return true;
    } catch (error) {
      return false;
    }
  };
  const canvasWidthResetObserved = installCanvasDimensionResetTrace('width');
  const canvasHeightResetObserved = installCanvasDimensionResetTrace('height');
  window.__bookwalkerCanvasResetObservationAvailable =
    canvasWidthResetObserved && canvasHeightResetObserved;
  window.__bookwalkerTransformTrace.diagnostics.canvasResetObservationAvailable =
    window.__bookwalkerCanvasResetObservationAvailable;

  const clearRect = CanvasRenderingContext2D.prototype.clearRect;
  const fillRect = CanvasRenderingContext2D.prototype.fillRect;
  const putImageData = CanvasRenderingContext2D.prototype.putImageData;
  if (typeof clearRect === 'function') {
    CanvasRenderingContext2D.prototype.clearRect = function(...args) {
      let operation = null;
      let observerState = null;
      let observerFlushedBefore = false;
      let transformBefore = null;
      let safetyBefore = null;
      let lostBefore = {available: false, value: null};
      let contentVersionBefore = null;
      let resetEpochBefore = null;
      let traceEpochBefore = null;
      let dimensionsBefore = null;
      let unknownMutationBefore = false;
      try {
        const traceBefore = window.__bookwalkerTransformTrace;
        if (traceBefore && window.__bookwalkerCaptureMode === 'native'
            && !internalCanvases.has(this.canvas)) {
          observerState = observeCanvasMutations(this.canvas);
          observerFlushedBefore = flushCanvasMutationObserver(this.canvas);
          transformBefore = readTransform(this);
          safetyBefore = contextSafetyInfo(this);
          lostBefore = contextLostState(this);
          contentVersionBefore = contentVersion(this.canvas);
          resetEpochBefore = Number(canvasResetEpochs.get(this.canvas) || 0);
          traceEpochBefore = traceBefore.traceEpoch;
          dimensionsBefore = {
            width: Number(this.canvas.width), height: Number(this.canvas.height),
          };
          unknownMutationBefore = canvasUnknownMutations.has(this.canvas);
        }
      } catch (error) {
        observerState = null;
        dimensionsBefore = null;
        traceEpochBefore = null;
      }
      try {
        const details = args.every(value => typeof value === 'number')
          ? rectangleDetails(args)
          : {arguments: [], relevantRectangle: null};
        operation = recordOperation('clearRect', this, details);
        if (operation && isFullClear(this.canvas, details.relevantRectangle)) {
          newSegment(this.canvas, operation.index, details.relevantRectangle);
        } else if (operation) {
          markUnsafe(this.canvas, operation.index, 'partial_clear');
        }
      } catch (error) {}
      const result = clearRect.apply(this, args);
      advanceContentVersion(this.canvas);
      if (operation && observerState && dimensionsBefore && traceEpochBefore !== null) {
        try {
          recordExecutedFullClearWitness(
            this, args, operation, observerState, observerFlushedBefore,
            transformBefore, safetyBefore, lostBefore, contentVersionBefore,
            resetEpochBefore, traceEpochBefore, dimensionsBefore,
            unknownMutationBefore,
          );
        } catch (error) {
          try {
            const trace = window.__bookwalkerTransformTrace;
            if (trace?.diagnostics) trace.diagnostics.rejectedFullClearWitnessCount += 1;
            const diagnostics = window.__bookwalkerNativeCaptureDiagnostics;
            if (diagnostics) diagnostics.rejectedFullClearWitnessCount += 1;
          } catch (ignored) {}
        }
      }
      return result;
    };
  }
  if (typeof fillRect === 'function') {
    CanvasRenderingContext2D.prototype.fillRect = function(...args) {
      let operation = null;
      try { operation = recordOperation('fillRect', this, rectangleDetails(args)); } catch (error) {}
      if (operation) markUnsafe(this.canvas, operation.index, 'fill_rect');
      const result = fillRect.apply(this, args);
      advanceContentVersion(this.canvas);
      return result;
    };
  }
  if (typeof putImageData === 'function') {
    CanvasRenderingContext2D.prototype.putImageData = function(...args) {
      let operation = null;
      try { operation = recordOperation('putImageData', this, {arguments: args.slice(1).map(value => Number(value))}); } catch (error) {}
      if (operation) markUnsafe(this.canvas, operation.index, 'put_image_data');
      const result = putImageData.apply(this, args);
      advanceContentVersion(this.canvas);
      return result;
    };
  }
  for (const name of ['setTransform', 'resetTransform', 'transform', 'translate', 'rotate', 'scale', 'reset']) {
    const originalMethod = CanvasRenderingContext2D.prototype[name];
    if (typeof originalMethod !== 'function') continue;
    CanvasRenderingContext2D.prototype[name] = function(...args) {
      let operation = null;
      if (name === 'reset') markContextSafetyUnknown(this);
      try { operation = recordOperation('transformChange', this, {method: name}); } catch (error) {}
      if (operation) markUnsafe(this.canvas, operation.index, 'transform_change');
      const result = originalMethod.apply(this, args);
      if (name === 'reset') {
        markContextKnownFresh(this);
        advanceContentVersion(this.canvas);
      }
      return result;
    };
  }
  for (const name of ['fillText', 'strokeText', 'fill', 'stroke', 'clip', 'save', 'restore']) {
    const originalMethod = CanvasRenderingContext2D.prototype[name];
    if (typeof originalMethod !== 'function') continue;
    CanvasRenderingContext2D.prototype[name] = function(...args) {
      let operation = null;
      const state = ensureContextState(this);
      if (name === 'clip') markContextSafetyUnknown(this);
      if (name === 'save' && state?.knownNoClip === true) state.saveStack.push(true);
      if (name === 'restore' && state?.knownNoClip === true && state.saveStack.length) {
        state.saveStack.pop();
      }
      try {
        operation = recordOperation('unsupportedMutation', this, {
          method: name,
          arguments: args.slice(0, 4).map(value => Number(value)),
        });
        if (operation) directRecordMutation(this.canvas, operation.index, name, operation);
      } catch (error) {}
      if (operation) markUnsafe(this.canvas, operation.index, `unsupported_${name}`);
      const result = originalMethod.apply(this, args);
      if (name === 'save' && state?.knownNoClip !== true) markContextSafetyUnknown(this);
      if (name === 'restore' && state?.knownNoClip !== true) markContextSafetyUnknown(this);
      if (!['clip', 'save', 'restore'].includes(name)) advanceContentVersion(this.canvas);
      return result;
    };
  }
})();
"""


def _strict_executed_clear_capture_allowed(
    native_capture_count: int,
    selected_draw_count: int,
) -> bool:
    """Keep the strict executed-clear promotion single-part only."""
    return native_capture_count == 1 and selected_draw_count == 1

_BOOKWALKER_NATIVE_RGBA_HASH_SCRIPT = """
async dataUrl => {
  if (typeof dataUrl !== 'string' || !dataUrl.startsWith('data:image/png;base64,')) {
    return null;
  }
  try {
    const response = await fetch(dataUrl);
    const blob = await response.blob();
    const bitmap = await createImageBitmap(blob);
    try {
      const canvas = document.createElement('canvas');
      window.__bookwalkerMarkInternalCanvas?.(canvas);
      canvas.width = bitmap.width;
      canvas.height = bitmap.height;
      const context = canvas.getContext('2d', {willReadFrequently: true});
      if (!context) return null;
      context.drawImage(bitmap, 0, 0);
      const rgba = context.getImageData(0, 0, bitmap.width, bitmap.height).data;
      const digest = await crypto.subtle.digest('SHA-256', rgba);
      const hash = Array.from(new Uint8Array(digest), value =>
        value.toString(16).padStart(2, '0')).join('');
      return {width: bitmap.width, height: bitmap.height, rgbaSha256: hash};
    } finally {
      bitmap.close();
    }
  } catch (error) {
    return null;
  }
}
"""

_BOOKWALKER_NATIVE_ANCHOR_SCRIPT = """
(element, expectedOperationIndex) => {
  if (typeof window.__bookwalkerP4BCurrentAnchor === 'function') {
    return window.__bookwalkerP4BCurrentAnchor(element, expectedOperationIndex);
  }
  const traceId = element?.getAttribute('data-bookwalker-trace-id') || null;
  const actualCanvasId = element ? String(
    window.__bookwalkerCanvasIdentity?.(element)
      || element?.getAttribute('data-bookwalker-trace-id') || '',
  ) : null;
  const calls = (window.__bookwalkerNativeDrawCalls || [])
    .filter(call => call.canvasId === traceId);
  const selected = calls.find(call =>
    (call?.operation?.index ?? call?.traceOperationIndex ?? null)
      === expectedOperationIndex) || null;
  const geometry = window.__bookwalkerDirectOneHopGeometryState?.(element) || null;
  const counter = document.querySelector('#pageSliderCounter')?.textContent || null;
  const geometryVersion = geometry?.geometryVersion ?? null;
  const targetContentVersion = geometry?.contentVersion ?? null;
  let bookIdentity = null;
  try {
    bookIdentity = new URL(window.location.href).searchParams.get('cid') || null;
  } catch (error) {}
  return {
    traceId,
    actualCanvasId,
    connected: Boolean(element?.isConnected && document.contains(element)),
    bookIdentity,
    counter,
    nativeCallCount: calls.length,
    operationIndices: calls.map(call =>
      call?.operation?.index ?? call?.traceOperationIndex ?? null),
    selected: selected ? {
      canvasId: selected?.canvasId ?? null,
      operationIndex: selected?.operation?.index ?? selected?.traceOperationIndex ?? null,
      sourceId: selected?.sourceId ?? null,
      sourceCanvasId: selected?.sourceCanvasId ?? null,
      traceEpoch: selected?.operation?.traceEpoch ?? selected?.traceEpoch ?? null,
      targetContentVersionAfter: selected?.targetContentVersionAfter ?? null,
      snapshotId: selected?.snapshotId ?? null,
      fullSourceSnapshotId: selected?.fullSourceSnapshotId ?? null,
      targetSnapshotId: selected?.targetSnapshotId ?? null,
      sourceRect: selected?.sourceRect ?? null,
      destination: selected?.destination ?? null,
      sourceContentVersion: selected?.sourceContentVersion ?? null,
    } : null,
    geometryToken: geometry?.token ?? null,
    traceEpoch: geometry?.traceEpoch ?? null,
    targetContentVersion,
    geometryVersion,
    geometryHistoryIncomplete: geometry?.geometryHistoryIncomplete ?? null,
    observerFlushed: geometry?.observerFlushed ?? null,
    observerAvailable: geometry?.observerAvailable ?? null,
    observerTakeRecordsAvailable: geometry?.observerTakeRecordsAvailable ?? null,
    unknownMutation: geometry?.unknownMutation ?? null,
    resetEpoch: geometry?.resetEpoch ?? null,
    canvasWidth: geometry?.width ?? null,
    canvasHeight: geometry?.height ?? null,
  };
}
"""

_BOOKWALKER_P4B_CURRENT_ROI_ANCHOR_SCRIPT = """
({expected, initialAnchor, destination, originalElement}) => {
  // Keep this target resolution aligned with BookWalkerAdapter._visible_canvas:
  // the current screen is authoritative when present, and a visible canvas
  // must be the exact object captured before the asynchronous proof work.
  const currentScreen = [
    ...document.querySelectorAll('#renderer .currentScreen canvas:not(.dummy)'),
  ];
  const pool = currentScreen.length
    ? currentScreen
    : [...document.querySelectorAll('#renderer canvas:not(.dummy)')];
  const visible = pool.filter(element => {
    if (!element?.isConnected || !document.contains(element)) return false;
    const style = window.getComputedStyle(element);
    const rect = element.getBoundingClientRect();
    return style.visibility !== 'hidden'
      && style.display !== 'none'
      && rect.width > 0
      && rect.height > 0
      && Number(element.width) > 0
      && Number(element.height) > 0;
  });
  if (!originalElement || !originalElement.isConnected
      || !document.contains(originalElement)) {
    return {available: false, exact: false, reason: 'original renderer element is unavailable'};
  }
  if (visible.length !== 1 || visible[0] !== originalElement) {
    return {available: false, exact: false, reason: 'current renderer canvas is missing or ambiguous'};
  }
  const element = originalElement;
  const actualTraceId = element.getAttribute('data-bookwalker-trace-id') || null;
  const actualCanvasId = String(window.__bookwalkerCanvasIdentity?.(element) || '');
  if (actualTraceId !== expected.traceId || actualCanvasId !== expected.actualCanvasId) {
    return {available: false, exact: false, reason: 'current capture target identity changed'};
  }
  const makeAnchor = () => {
    if (typeof window.__bookwalkerP4BCurrentAnchor === 'function') {
      return window.__bookwalkerP4BCurrentAnchor(element, expected.operationIndex);
    }
    const traceId = element.getAttribute('data-bookwalker-trace-id') || null;
    const actualCanvasId = String(window.__bookwalkerCanvasIdentity?.(element) || '');
    const calls = (window.__bookwalkerNativeDrawCalls || [])
      .filter(call => call?.canvasId === traceId);
    const selected = calls.find(call => (
      (call?.operation?.index ?? call?.traceOperationIndex ?? null)
      === expected.operationIndex
    )) || null;
    const geometry = window.__bookwalkerDirectOneHopGeometryState?.(element) || null;
    let bookIdentity = null;
    try { bookIdentity = new URL(window.location.href).searchParams.get('cid') || null; }
    catch (error) {}
    return {
      traceId,
      actualCanvasId,
      connected: Boolean(element.isConnected && document.contains(element)),
      bookIdentity,
      counter: document.querySelector('#pageSliderCounter')?.textContent || null,
      geometryToken: geometry?.token ?? null,
      geometryVersion: geometry?.geometryVersion ?? null,
      geometryHistoryIncomplete: geometry?.geometryHistoryIncomplete ?? null,
      observerFlushed: geometry?.observerFlushed ?? null,
      observerAvailable: geometry?.observerAvailable ?? null,
      observerTakeRecordsAvailable: geometry?.observerTakeRecordsAvailable ?? null,
      unknownMutation: geometry?.unknownMutation ?? null,
      resetEpoch: geometry?.resetEpoch ?? null,
      canvasWidth: geometry?.width ?? null,
      canvasHeight: geometry?.height ?? null,
      targetContentVersion: geometry?.contentVersion ?? null,
      selected: selected ? {
        canvasId: selected.canvasId ?? null,
        operationIndex: selected?.operation?.index ?? selected?.traceOperationIndex ?? null,
        sourceId: selected.sourceId ?? null,
        sourceCanvasId: selected.sourceCanvasId ?? null,
        sourceContentVersion: selected.sourceContentVersion ?? null,
        fullSourceSnapshotId: selected.fullSourceSnapshotId ?? null,
        targetSnapshotId: selected.targetSnapshotId ?? null,
        targetContentVersionAfter: selected.targetContentVersionAfter ?? null,
        sourceRect: selected.sourceRect ?? null,
        destination: selected.destination ?? null,
      } : null,
    };
  };
  const valuePresent = value => (
    value !== null && value !== undefined && value !== ''
  );
  const sameValue = (left, right) => (
    left === right || JSON.stringify(left) === JSON.stringify(right)
  );
  const latestCallSummary = () => (window.__bookwalkerNativeDrawCalls || [])
    .filter(call => call?.canvasId === expected.traceId)
    .slice(-4)
    .map(call => ({
      operationIndex: call?.operation?.index ?? call?.traceOperationIndex ?? null,
      traceEpoch: call?.operation?.traceEpoch ?? call?.traceEpoch ?? null,
      canvasId: call?.canvasId ?? null,
      sourceId: call?.sourceId ?? null,
      sourceCanvasId: call?.sourceCanvasId ?? null,
      sourceContentVersion: call?.sourceContentVersion ?? null,
      targetContentVersionAfter: call?.targetContentVersionAfter ?? null,
      sourceRect: call?.sourceRect ?? null,
      destination: call?.destination ?? null,
      fullSourceSnapshotId: call?.fullSourceSnapshotId ?? null,
      targetSnapshotId: call?.targetSnapshotId ?? null,
    }));
  const requiredFields = [
    'traceId', 'actualCanvasId', 'connected', 'bookIdentity', 'counter',
    'geometryToken', 'traceEpoch', 'geometryVersion', 'targetContentVersion',
    'geometryHistoryIncomplete', 'observerFlushed', 'observerAvailable',
    'observerTakeRecordsAvailable', 'unknownMutation', 'resetEpoch',
    'canvasWidth', 'canvasHeight',
  ];
  const selectedFields = [
    'canvasId', 'operationIndex', 'sourceId', 'sourceCanvasId',
    'traceEpoch', 'sourceContentVersion', 'fullSourceSnapshotId', 'targetSnapshotId',
    'targetContentVersionAfter', 'sourceRect', 'destination',
  ];
  const sameAnchor = (left, right) => {
    if (!left || !right) return false;
    if (requiredFields.some(field => (
      !valuePresent(left[field]) || !valuePresent(right[field])
      || !sameValue(left[field], right[field])
    ))) return false;
    if (left.connected !== true || right.connected !== true
        || left.geometryHistoryIncomplete !== false
        || right.geometryHistoryIncomplete !== false
        || left.observerFlushed !== true || right.observerFlushed !== true
        || left.observerAvailable !== true || right.observerAvailable !== true
        || left.observerTakeRecordsAvailable !== true
        || right.observerTakeRecordsAvailable !== true
        || left.unknownMutation !== false || right.unknownMutation !== false) return false;
    if (!left.selected || !right.selected) return false;
    if (!Number.isInteger(left.traceEpoch) || left.traceEpoch <= 0
        || !Number.isInteger(right.traceEpoch) || right.traceEpoch <= 0
        || !Number.isInteger(left.selected.traceEpoch) || left.selected.traceEpoch <= 0
        || !Number.isInteger(right.selected.traceEpoch) || right.selected.traceEpoch <= 0
        || left.traceEpoch !== left.selected.traceEpoch
        || right.traceEpoch !== right.selected.traceEpoch) return false;
    return selectedFields.every(field => (
      valuePresent(left.selected[field])
      && valuePresent(right.selected[field])
      && sameValue(left.selected[field], right.selected[field])
    ));
  };
  const before = makeAnchor();
  if (!sameAnchor(initialAnchor, before)) {
    return {
      available: false, exact: false, reason: 'initial renderer anchor changed',
      initial: initialAnchor, before, latestNativeCalls: latestCallSummary(),
    };
  }
  const selected = before.selected;
  if (!selected || selected.canvasId !== expected.traceId
      || selected.operationIndex !== expected.operationIndex
      || selected.sourceId !== expected.sourceId
      || selected.sourceCanvasId !== expected.sourceCanvasId
      || selected.traceEpoch !== expected.selectedTraceEpoch
      || selected.sourceContentVersion !== expected.sourceContentVersion
      || selected.fullSourceSnapshotId !== expected.fullSourceSnapshotId
      || selected.targetSnapshotId !== expected.targetSnapshotId
      || selected.targetContentVersionAfter !== expected.targetContentVersionAfter
      || !sameValue(selected.sourceRect, expected.sourceRect)
      || !sameValue(selected.destination, expected.destination)) {
    return {available: false, exact: false, reason: 'selected renderer B anchor mismatch', before};
  }
  const expectedSnapshot = window.__bookwalkerNativeSnapshots?.get(
    String(expected.targetSnapshotId)
  );
  if (!expectedSnapshot) {
    return {available: false, exact: false, reason: 'immutable renderer ROI snapshot unavailable', before};
  }
  let current = null;
  try {
    const x = Number(destination?.x), y = Number(destination?.y);
    const width = Number(destination?.width), height = Number(destination?.height);
    if (![x, y, width, height].every(Number.isInteger)
        || width <= 0 || height <= 0
        || x < 0 || y < 0 || x + width > element.width || y + height > element.height
        || expectedSnapshot.width !== width || expectedSnapshot.height !== height) {
      return {available: false, exact: false, reason: 'current ROI geometry unavailable', before};
    }
    const expectedCanvas = document.createElement('canvas');
    window.__bookwalkerMarkInternalCanvas?.(expectedCanvas);
    expectedCanvas.width = width; expectedCanvas.height = height;
    const expectedContext = expectedCanvas.getContext('2d');
    const currentContext = element.getContext('2d');
    if (!expectedContext || !currentContext) {
      return {available: false, exact: false, reason: 'current ROI context unavailable', before};
    }
    expectedContext.drawImage(expectedSnapshot, 0, 0);
    const actualData = currentContext.getImageData(x, y, width, height).data;
    const expectedData = expectedContext.getImageData(0, 0, width, height).data;
    let differingPixels = 0; let maxChannelDifference = 0;
    for (let index = 0; index < actualData.length; index += 4) {
      let different = false;
      for (let channel = 0; channel < 4; channel += 1) {
        const difference = Math.abs(actualData[index + channel] - expectedData[index + channel]);
        maxChannelDifference = Math.max(maxChannelDifference, difference);
        different ||= difference !== 0;
      }
      if (different) differingPixels += 1;
    }
    current = {
      available: true,
      dimensions_equal: true,
      exact: differingPixels === 0,
      differing_pixel_count: differingPixels,
      max_channel_difference: maxChannelDifference,
    };
  } finally {}
  const after = makeAnchor();
  if (!sameAnchor(before, after) || !sameAnchor(initialAnchor, after)) {
    return {
      available: true, exact: false, reason: 'final renderer anchor changed',
      current, before, after, latestNativeCalls: latestCallSummary(),
    };
  }
  return {available: true, exact: current?.exact === true, current, before, after,
    reason: current?.exact === true ? 'current DOM ROI exact' : 'current DOM ROI mismatch'};
}
"""

_SELECTED_COMPLETED_MAPPINGS_COMPACT_SCRIPT = """
(requestedMappingIds) => {
  try {
    const trace = window.__bookwalkerTransformTrace;
    const completedMappings = Array.isArray(trace?.completedMappings)
      ? trace.completedMappings
      : [];
    const activeSegments = trace?.activeSegments
      && typeof trace.activeSegments === 'object'
      ? Object.values(trace.activeSegments)
      : [];
    const requested = Array.isArray(requestedMappingIds)
      ? requestedMappingIds.map(value => String(value))
      : [];
    const requestedSet = new Set(requested);
    const returned = completedMappings.filter(record => (
      record
      && record.mappingId !== null
      && record.mappingId !== undefined
      && requestedSet.has(String(record.mappingId))
    ));
    const has = (object, key) => (
      object !== null
      && typeof object === 'object'
      && Object.prototype.hasOwnProperty.call(object, key)
    );
    const required = (object, key) => {
      if (!has(object, key) || object[key] === undefined) {
        throw new Error(`compact field is missing: ${key}`);
      }
      return object[key];
    };
    const addTableValue = (table, indexes, value) => {
      const key = JSON.stringify(value);
      if (!indexes.has(key)) {
        indexes.set(key, table.length);
        table.push(value);
      }
      return indexes.get(key);
    };
    const rectangle = value => [
      required(value, 'x'),
      required(value, 'y'),
      required(value, 'width'),
      required(value, 'height'),
    ];
    const transform = value => [
      required(value, 'a'),
      required(value, 'b'),
      required(value, 'c'),
      required(value, 'd'),
      required(value, 'e'),
      required(value, 'f'),
    ];
    const compactMapping = mapping => {
      if (!mapping || typeof mapping !== 'object') {
        throw new Error('compact mapping is not an object');
      }
      const sources = [];
      const sourceIndexes = new Map();
      const targets = [];
      const targetIndexes = new Map();
      const transforms = [];
      const transformIndexes = new Map();
      const composites = [];
      const compositeIndexes = new Map();
      const filters = [];
      const filterIndexes = new Map();
      const tileRows = [];
      const tileVersions = [];
      const tiles = required(mapping, 'tileDraws');
      if (!Array.isArray(tiles)) throw new Error('compact tile records are not a list');
      for (const tile of tiles) {
        const source = required(tile, 'source');
        const target = required(tile, 'target');
        const sourceCanvasId = has(source, 'canvasId')
          ? source.canvasId
          : has(source, 'sourceCanvasId') ? source.sourceCanvasId : null;
        if (sourceCanvasId === undefined) throw new Error('compact source canvas id is missing');
        const sourceRow = [
          required(source, 'constructor'),
          required(source, 'sourceId'),
          required(source, 'width'),
          required(source, 'height'),
          sourceCanvasId,
          source.resetEpoch ?? null,
        ];
        const targetRow = [
          required(target, 'canvasId'),
          required(target, 'width'),
          required(target, 'height'),
          target.resetEpoch ?? null,
        ];
        const sourceIndex = addTableValue(sources, sourceIndexes, sourceRow);
        const targetIndex = addTableValue(targets, targetIndexes, targetRow);
        const transformIndex = addTableValue(
          transforms,
          transformIndexes,
          transform(required(tile, 'transform')),
        );
        const compositeIndex = addTableValue(
          composites,
          compositeIndexes,
          required(tile, 'globalCompositeOperation'),
        );
        const filterIndex = addTableValue(
          filters,
          filterIndexes,
          required(tile, 'filter'),
        );
        tileRows.push([
          required(tile, 'operationIndex'),
          sourceIndex,
          targetIndex,
          ...rectangle(required(tile, 'sourceRect')),
          ...rectangle(required(tile, 'destination')),
          transformIndex,
          required(tile, 'globalAlpha'),
          compositeIndex,
          filterIndex,
        ]);
        tileVersions.push([
          tile.sourceContentVersion ?? null,
          tile.targetContentVersionBefore ?? null,
          tile.targetContentVersionAfter ?? null,
        ]);
      }
      const compact = {};
      for (const key of [
        'mappingId',
        'rendererOperationIndex',
        'rendererTarget',
        'sourceCanvas',
        'rendererSourceRect',
        'rendererDestination',
        'rendererTransform',
        'rendererAlpha',
        'rendererComposite',
        'rendererFilter',
        'segmentClearOperationIndex',
        'segmentClearRectangle',
        'segmentFirstTileOperationIndex',
        'segmentLastTileOperationIndex',
        'segmentTileCount',
        'segmentExpectedTileCount',
        'unsafeOperationCount',
        'firstUnsafeOperationIndex',
        'unsafeOperationTypes',
        'segmentOverflow',
        'sourceIds',
      ]) compact[key] = required(mapping, key);
      for (const key of [
        'segmentClearTarget', 'segmentResetKind', 'segmentResetEpoch',
        'segmentDrawTarget', 'segmentUnknownMutation',
        'segmentResetObservationAvailable',
        'segmentMutationObserverAvailable',
        'segmentMutationObserverTakeRecordsAvailable',
        'segmentExecutedFullClearWitness',
        'segmentExecutedFullClearWitnessRejection',
        'segmentTraceEpoch',
        'sourceSnapshotId',
        'sourceSnapshotError',
        'sourceSnapshotContentVersion',
      ]) {
        if (has(mapping, key)) compact[key] = mapping[key];
      }
      compact.nonImageBitmapDraws = has(mapping, 'nonImageBitmapDraws')
        ? required(mapping, 'nonImageBitmapDraws') : [];
      compact.sources = sources;
      compact.targets = targets;
      compact.transforms = transforms;
      compact.composites = composites;
      compact.filters = filters;
      compact.tileRows = tileRows;
      compact.tileVersions = tileVersions;
      return compact;
    };
    const tileCount = mappings => mappings.reduce((total, mapping) => (
      total + (Array.isArray(mapping?.tileDraws) ? mapping.tileDraws.length : 0)
    ), 0);
    const mappingSummary = mapping => {
      const sourceIds = [];
      for (const tile of (Array.isArray(mapping?.tileDraws) ? mapping.tileDraws : [])) {
        const sourceId = tile?.source?.sourceId;
        if (typeof sourceId === 'string' && !sourceIds.includes(sourceId)) {
          sourceIds.push(sourceId);
        }
        if (sourceIds.length >= 4) break;
      }
      return {
        mappingId: required(mapping, 'mappingId'),
        sourceCanvasId: required(mapping, 'sourceCanvas').canvasId,
        targetCanvasId: required(mapping, 'rendererTarget').canvasId,
        rendererOperationIndex: required(mapping, 'rendererOperationIndex'),
        segmentClearOperationIndex: required(mapping, 'segmentClearOperationIndex'),
        segmentFirstTileOperationIndex: required(mapping, 'segmentFirstTileOperationIndex'),
        segmentLastTileOperationIndex: required(mapping, 'segmentLastTileOperationIndex'),
        segmentTileCount: required(mapping, 'segmentTileCount'),
        sourceImageBitmapIds: sourceIds,
        sourceDimensions: {
          width: required(mapping, 'sourceCanvas').width,
          height: required(mapping, 'sourceCanvas').height,
        },
        targetDimensions: {
          width: required(mapping, 'rendererTarget').width,
          height: required(mapping, 'rendererTarget').height,
        },
        sourceResetEpoch: required(mapping, 'sourceCanvas').resetEpoch ?? null,
        targetResetEpoch: required(mapping, 'rendererTarget').resetEpoch ?? null,
        clearTarget: mapping.segmentClearTarget || null,
        resetKind: mapping.segmentResetKind || null,
        resetEpoch: mapping.segmentResetEpoch ?? null,
        drawTarget: mapping.segmentDrawTarget || null,
        unknownMutation: mapping.segmentUnknownMutation === true,
        resetObservationAvailable: mapping.segmentResetObservationAvailable === true,
        mutationObserverAvailable: mapping.segmentMutationObserverAvailable === true,
        mutationObserverTakeRecordsAvailable:
          mapping.segmentMutationObserverTakeRecordsAvailable === true,
        executedFullClearWitness: mapping.segmentExecutedFullClearWitness || null,
      };
    };
    const activeTileCount = activeSegments.reduce((total, segment) => (
      total + (Array.isArray(segment?.tileDraws) ? segment.tileDraws.length : 0)
    ), 0);
    const compactMappings = returned.map(compactMapping);
    const returnedMappingIds = new Set(
      returned
        .filter(record => record.mappingId !== null && record.mappingId !== undefined)
        .map(record => String(record.mappingId)),
    );
    const compactCounts = compactMappings.reduce((counts, mapping) => {
      counts.source += mapping.sources.length;
      counts.target += mapping.targets.length;
      counts.transform += mapping.transforms.length;
      counts.composite += mapping.composites.length;
      counts.filter += mapping.filters.length;
      return counts;
    }, {source: 0, target: 0, transform: 0, composite: 0, filter: 0});
    return {
      transportVersion: 1,
      compactMappings,
      retainedCompletedMappingSummaries: completedMappings.map(mappingSummary),
      retainedCompletedMappingCount: completedMappings.length,
      retainedCompletedTileRecordCount: tileCount(completedMappings),
      activeSegmentCount: activeSegments.length,
      activeTileRecordCount: activeTileCount,
      droppedCompletedMappingCount: Number.isFinite(trace?.droppedCompletedMappingCount)
        ? Number(trace.droppedCompletedMappingCount) : 0,
      droppedActiveSegmentCount: Number.isFinite(trace?.droppedActiveSegmentCount)
        ? Number(trace.droppedActiveSegmentCount) : 0,
      requestedMappingCount: requestedSet.size,
      returnedCompletedMappingCount: compactMappings.length,
      returnedTileRecordCount: tileCount(returned),
      missingMappingCount: [...requestedSet]
        .filter(mappingId => !returnedMappingIds.has(mappingId)).length,
      compactSourceTableCount: compactCounts.source,
      compactTargetTableCount: compactCounts.target,
      compactTransformTableCount: compactCounts.transform,
      compactCompositeTableCount: compactCounts.composite,
      compactFilterTableCount: compactCounts.filter,
    };
  } catch (error) {
    return {transportVersion: 1, transportError: String(error)};
  }
}
"""

_MATERIALIZE_NATIVE_SOURCE_SCRIPT = """
items => items.map(item => {
  try {
    const copy = window.__bookwalkerMaterializeNativeSourceCrop?.(item);
    const full = item.fullSourceSnapshotId == null ? null
      : window.__bookwalkerMaterializeNativeSourceCrop?.({...item, snapshotId: item.fullSourceSnapshotId});
    const target = item.targetSnapshotId == null ? null
      : window.__bookwalkerMaterializeNativeSourceCrop?.({...item, snapshotId: item.targetSnapshotId});
    return {
      dataUrl: copy?.dataUrl || null,
      error: copy ? copy.error : 'native source crop unavailable',
      fullSourceDataUrl: full?.dataUrl || null,
      fullSourceError: full ? full.error : null,
      targetDataUrl: target?.dataUrl || null,
      targetError: target ? target.error : null,
    };
  } catch (error) {
    return {dataUrl: null, error: String(error)};
  }
})
"""

_PIXEL_EXACT_COMPARISON_SCRIPT = """
async ({reconstructed, native}) => {
  async function load(dataUrl) {
    const response = await fetch(dataUrl);
    return await createImageBitmap(await response.blob());
  }
  const left = await load(reconstructed);
  const right = await load(native);
  try {
    if (left.width !== right.width || left.height !== right.height) {
      return {available: true, dimensions_equal: false, exact: false};
    }
    const canvas = document.createElement('canvas');
    window.__bookwalkerMarkInternalCanvas?.(canvas);
    canvas.width = left.width;
    canvas.height = left.height;
    const context = canvas.getContext('2d', {willReadFrequently: true});
    if (!context) return {available: false, exact: false, reason: '2d context unavailable'};
    context.drawImage(left, 0, 0);
    const leftData = context.getImageData(0, 0, left.width, left.height).data;
    context.clearRect(0, 0, left.width, left.height);
    context.drawImage(right, 0, 0);
    const rightData = context.getImageData(0, 0, right.width, right.height).data;
    let differingPixels = 0;
    let maxChannelDifference = 0;
    for (let index = 0; index < leftData.length; index += 4) {
      let different = false;
      for (let channel = 0; channel < 4; channel += 1) {
        const difference = Math.abs(leftData[index + channel] - rightData[index + channel]);
        maxChannelDifference = Math.max(maxChannelDifference, difference);
        different ||= difference !== 0;
      }
      if (different) differingPixels += 1;
    }
    return {
      available: true,
      dimensions_equal: true,
      exact: differingPixels === 0,
      differing_pixel_count: differingPixels,
      max_channel_difference: maxChannelDifference,
    };
  } finally {
    left.close();
    right.close();
  }
}
"""

_SCALED_SOURCE_PIXEL_EXACT_COMPARISON_SCRIPT = """
async ({reconstructed, native, sourceRect, destination, targetDimensions,
        imageSmoothingEnabled, imageSmoothingQuality}) => {
  async function load(dataUrl) {
    const response = await fetch(dataUrl);
    return await createImageBitmap(await response.blob());
  }
  if (typeof imageSmoothingEnabled !== 'boolean'
      || typeof imageSmoothingQuality !== 'string'
      || !['low', 'medium', 'high'].includes(imageSmoothingQuality)) {
    return {available: false, exact: false, reason: 'smoothing metadata unavailable'};
  }
  const left = await load(reconstructed);
  const right = await load(native);
  try {
    // The proven live operation has an HTMLCanvasElement source.  Restore the
    // source-native JPEG into a source-size canvas before reproducing the
    // scaled draw so the diagnostic uses the same source kind as the trace.
    const sourceCanvas = document.createElement('canvas');
    window.__bookwalkerMarkInternalCanvas?.(sourceCanvas);
    sourceCanvas.width = left.width;
    sourceCanvas.height = left.height;
    const sourceContext = sourceCanvas.getContext('2d');
    if (!sourceContext) {
      return {available: false, exact: false, reason: 'source 2d context unavailable'};
    }
    sourceContext.drawImage(left, 0, 0);
    const targetWidth = Number(targetDimensions?.width);
    const targetHeight = Number(targetDimensions?.height);
    if (!Number.isInteger(targetWidth) || !Number.isInteger(targetHeight)
        || targetWidth <= 0 || targetHeight <= 0
        || right.width !== targetWidth || right.height !== targetHeight) {
      return {available: true, dimensions_equal: false, exact: false};
    }
    const canvas = document.createElement('canvas');
    window.__bookwalkerMarkInternalCanvas?.(canvas);
    canvas.width = targetWidth;
    canvas.height = targetHeight;
    const context = canvas.getContext('2d', {willReadFrequently: true});
    if (!context) return {available: false, exact: false, reason: '2d context unavailable'};
    context.imageSmoothingEnabled = imageSmoothingEnabled;
    context.imageSmoothingQuality = imageSmoothingQuality;
    const sx = Number(sourceRect?.x);
    const sy = Number(sourceRect?.y);
    const sw = Number(sourceRect?.width);
    const sh = Number(sourceRect?.height);
    const dx = Number(destination?.x);
    const dy = Number(destination?.y);
    const dw = Number(destination?.width);
    const dh = Number(destination?.height);
    context.drawImage(sourceCanvas, sx, sy, sw, sh, dx, dy, dw, dh);
    const leftData = context.getImageData(0, 0, targetWidth, targetHeight).data;
    context.clearRect(0, 0, targetWidth, targetHeight);
    context.drawImage(right, 0, 0);
    const rightData = context.getImageData(0, 0, targetWidth, targetHeight).data;
    let differingPixels = 0;
    let maxChannelDifference = 0;
    for (let index = 0; index < leftData.length; index += 4) {
      let different = false;
      for (let channel = 0; channel < 4; channel += 1) {
        const difference = Math.abs(leftData[index + channel] - rightData[index + channel]);
        maxChannelDifference = Math.max(maxChannelDifference, difference);
        different ||= difference !== 0;
      }
      if (different) differingPixels += 1;
    }
    return {
      available: true,
      dimensions_equal: true,
      exact: differingPixels === 0,
      differing_pixel_count: differingPixels,
      max_channel_difference: maxChannelDifference,
    };
  } finally {
    left.close();
    right.close();
  }
}
"""


_DIRECT_ONE_HOP_PIXEL_EXACT_COMPARISON_SCRIPT = """
async ({candidate, sourceSnapshot, intermediate, sourceB, targetSnapshot, current,
        copySourceRect, copyDestination, rendererSourceRect, rendererDestination,
        intermediateDimensions, rendererDimensions, copySmoothingEnabled,
        copySmoothingQuality, rendererSmoothingEnabled, rendererSmoothingQuality}) => {
  async function load(dataUrl) {
    if (typeof dataUrl !== 'string' || !dataUrl) return null;
    const response = await fetch(dataUrl);
    return await createImageBitmap(await response.blob());
  }
  const raw = await load(candidate);
  const expectedA = await load(sourceSnapshot);
  const expectedB = await load(intermediate);
  const expectedSourceB = await load(sourceB);
  const expectedTarget = await load(targetSnapshot);
  const expectedCurrent = await load(current);
  if (!raw || !expectedA || !expectedB || !expectedSourceB || !expectedTarget || !expectedCurrent) {
    raw?.close(); expectedA?.close(); expectedB?.close();
    expectedSourceB?.close();
    expectedTarget?.close(); expectedCurrent?.close();
    return {available: false, exact: false, reason: 'direct immutable snapshot unavailable'};
  }
  const compare = (actual, expected, width, height, x = 0, y = 0) => {
    if (!expected || expected.width !== width || expected.height !== height) {
      return {available: true, dimensions_equal: false, exact: false,
        differing_pixel_count: null, max_channel_difference: null};
    }
    if (x < 0 || y < 0 || x + width > actual.canvas.width || y + height > actual.canvas.height) {
      return {available: true, dimensions_equal: true, exact: false,
        reason: 'comparison rectangle outside replay canvas'};
    }
    const expectedCanvas = document.createElement('canvas');
    window.__bookwalkerMarkInternalCanvas?.(expectedCanvas);
    expectedCanvas.width = width; expectedCanvas.height = height;
    const expectedContext = expectedCanvas.getContext('2d');
    if (!expectedContext) return {available: false, exact: false, reason: 'expected context unavailable'};
    expectedContext.drawImage(expected, 0, 0);
    const actualData = actual.getImageData(x, y, width, height).data;
    const expectedData = expectedContext.getImageData(0, 0, width, height).data;
    let differing = 0; let maxDifference = 0;
    for (let index = 0; index < actualData.length; index += 4) {
      let different = false;
      for (let channel = 0; channel < 4; channel += 1) {
        const difference = Math.abs(actualData[index + channel] - expectedData[index + channel]);
        maxDifference = Math.max(maxDifference, difference);
        different ||= difference !== 0;
      }
      if (different) differing += 1;
    }
    return {available: true, dimensions_equal: true, exact: differing === 0,
      differing_pixel_count: differing, max_channel_difference: maxDifference};
  };
  const makeCanvas = (width, height) => {
    const canvas = document.createElement('canvas');
    window.__bookwalkerMarkInternalCanvas?.(canvas);
    canvas.width = width; canvas.height = height;
    return canvas;
  };
  try {
    if (typeof copySmoothingEnabled !== 'boolean'
        || !['low', 'medium', 'high'].includes(copySmoothingQuality)
        || typeof rendererSmoothingEnabled !== 'boolean'
        || !['low', 'medium', 'high'].includes(rendererSmoothingQuality)) {
      return {available: false, exact: false, reason: 'smoothing metadata unavailable'};
    }
    const sourceCanvas = makeCanvas(raw.width, raw.height);
    const sourceContext = sourceCanvas.getContext('2d');
    if (!sourceContext) return {available: false, exact: false, reason: 'source context unavailable'};
    sourceContext.drawImage(raw, 0, 0);
    const aCompare = compare(sourceContext, expectedA, raw.width, raw.height);
    if (!aCompare.exact) return {available: true, exact: false, source: aCompare, reason: 'candidate to A mismatch'};

    const bWidth = Number(intermediateDimensions?.width);
    const bHeight = Number(intermediateDimensions?.height);
    if (!Number.isInteger(bWidth) || !Number.isInteger(bHeight) || bWidth <= 0 || bHeight <= 0) {
      return {available: false, exact: false, reason: 'intermediate dimensions unavailable'};
    }
    const bCanvas = makeCanvas(bWidth, bHeight);
    const bContext = bCanvas.getContext('2d');
    if (!bContext) return {available: false, exact: false, reason: 'intermediate context unavailable'};
    bContext.imageSmoothingEnabled = copySmoothingEnabled;
    bContext.imageSmoothingQuality = copySmoothingQuality;
    const csx = Number(copySourceRect?.x), csy = Number(copySourceRect?.y);
    const csw = Number(copySourceRect?.width), csh = Number(copySourceRect?.height);
    const cdx = Number(copyDestination?.x), cdy = Number(copyDestination?.y);
    const cdw = Number(copyDestination?.width), cdh = Number(copyDestination?.height);
    if (![csx,csy,csw,csh,cdx,cdy,cdw,cdh].every(Number.isFinite)) {
      return {available: false, exact: false, reason: 'copy geometry unavailable'};
    }
    bContext.drawImage(sourceCanvas, csx, csy, csw, csh, cdx, cdy, cdw, cdh);
    const bCompare = compare(bContext, expectedB, bWidth, bHeight);
    if (!bCompare.exact) return {available: true, exact: false, source: aCompare, intermediate: bCompare, reason: 'A to B mismatch'};
    const sourceBCompare = compare(bContext, expectedSourceB, bWidth, bHeight);
    if (!sourceBCompare.exact) return {available: true, exact: false, source: aCompare, intermediate: bCompare, sourceB: sourceBCompare, reason: 'B source changed between hops'};

    const rw = Number(rendererDimensions?.width), rh = Number(rendererDimensions?.height);
    if (!Number.isInteger(rw) || !Number.isInteger(rh) || rw <= 0 || rh <= 0) {
      return {available: false, exact: false, reason: 'renderer dimensions unavailable'};
    }
    const rendererCanvas = makeCanvas(rw, rh);
    const rendererContext = rendererCanvas.getContext('2d');
    if (!rendererContext) return {available: false, exact: false, reason: 'renderer context unavailable'};
    rendererContext.imageSmoothingEnabled = rendererSmoothingEnabled;
    rendererContext.imageSmoothingQuality = rendererSmoothingQuality;
    const rsx = Number(rendererSourceRect?.x), rsy = Number(rendererSourceRect?.y);
    const rsw = Number(rendererSourceRect?.width), rsh = Number(rendererSourceRect?.height);
    const rdx = Number(rendererDestination?.x), rdy = Number(rendererDestination?.y);
    const rdw = Number(rendererDestination?.width), rdh = Number(rendererDestination?.height);
    if (![rsx,rsy,rsw,rsh,rdx,rdy,rdw,rdh].every(Number.isFinite)) {
      return {available: false, exact: false, reason: 'renderer geometry unavailable'};
    }
    rendererContext.drawImage(bCanvas, rsx, rsy, rsw, rsh, rdx, rdy, rdw, rdh);
    const targetWidth = expectedTarget.width, targetHeight = expectedTarget.height;
    const targetCompare = compare(rendererContext, expectedTarget, targetWidth, targetHeight, rdx, rdy);
    if (!targetCompare.exact) return {available: true, exact: false, source: aCompare, intermediate: bCompare, sourceB: sourceBCompare, target: targetCompare, reason: 'B to target mismatch'};
    const currentCompare = compare(rendererContext, expectedCurrent, targetWidth, targetHeight, rdx, rdy);
    return {available: true, exact: currentCompare.exact, source: aCompare,
      intermediate: bCompare, sourceB: sourceBCompare, target: targetCompare, current: currentCompare,
      reason: currentCompare.exact ? 'direct one-hop output-equivalence exact' : 'current ROI mismatch'};
  } finally {
    raw.close(); expectedA.close(); expectedB.close(); expectedSourceB.close();
    expectedTarget.close(); expectedCurrent.close();
  }
}
"""


_CROPPED_ONE_HOP_PIXEL_EXACT_COMPARISON_SCRIPT = """
async ({reconstructed, intermediate, finalTarget, copySourceRect, copyDestination,
        finalSourceRect, finalDestination, intermediateDimensions,
        finalCanvasDimensions,
        sourceSnapshot,
        copySmoothingEnabled, copySmoothingQuality, finalSmoothingEnabled,
        finalSmoothingQuality}) => {
  async function load(dataUrl) {
    if (typeof dataUrl !== 'string' || !dataUrl) return null;
    const response = await fetch(dataUrl);
    return await createImageBitmap(await response.blob());
  }
  const left = await load(reconstructed);
  const expectedSource = await load(sourceSnapshot);
  const expectedIntermediate = await load(intermediate);
  const expectedFinal = await load(finalTarget);
  if (!left || !expectedSource || !expectedIntermediate || !expectedFinal) {
    left?.close(); expectedSource?.close(); expectedIntermediate?.close(); expectedFinal?.close();
    return {available: false, exact: false, reason: 'immutable chain snapshot unavailable'};
  }
  const compare = (actual, expected, width, height, actualX = 0, actualY = 0) => {
    if (expected.width !== width || expected.height !== height) {
      return {available: true, dimensions_equal: false, exact: false};
    }
    const expectedCanvas = document.createElement('canvas');
    window.__bookwalkerMarkInternalCanvas?.(expectedCanvas);
    expectedCanvas.width = width; expectedCanvas.height = height;
    const expectedContext = expectedCanvas.getContext('2d');
    if (!expectedContext) return {available: false, exact: false, reason: 'expected context unavailable'};
    expectedContext.drawImage(expected, 0, 0);
    if (actualX < 0 || actualY < 0
        || actualX + width > actual.canvas.width || actualY + height > actual.canvas.height) {
      return {available: true, dimensions_equal: true, exact: false,
        reason: 'comparison rectangle outside replay canvas'};
    }
    const actualData = actual.getImageData(actualX, actualY, width, height).data;
    const expectedData = expectedContext.getImageData(0, 0, width, height).data;
    let differing = 0; let maxDifference = 0;
    for (let index = 0; index < actualData.length; index += 4) {
      let pixelDifferent = false;
      for (let channel = 0; channel < 4; channel += 1) {
        const difference = Math.abs(actualData[index + channel] - expectedData[index + channel]);
        maxDifference = Math.max(maxDifference, difference);
        pixelDifferent ||= difference !== 0;
      }
      if (pixelDifferent) differing += 1;
    }
    return {available: true, dimensions_equal: true, exact: differing === 0,
      differing_pixel_count: differing, max_channel_difference: maxDifference};
  };
  try {
    if (typeof copySmoothingEnabled !== 'boolean' || typeof finalSmoothingEnabled !== 'boolean'
        || !['low', 'medium', 'high'].includes(copySmoothingQuality)
        || !['low', 'medium', 'high'].includes(finalSmoothingQuality)) {
      return {available: false, exact: false, reason: 'chain smoothing metadata unavailable'};
    }
    const intermediateWidth = Number(intermediateDimensions?.width);
    const intermediateHeight = Number(intermediateDimensions?.height);
    if (!Number.isInteger(intermediateWidth) || !Number.isInteger(intermediateHeight)
        || intermediateWidth <= 0 || intermediateHeight <= 0) {
      return {available: false, exact: false, reason: 'intermediate dimensions unavailable'};
    }
    const sourceCanvas = document.createElement('canvas');
    window.__bookwalkerMarkInternalCanvas?.(sourceCanvas);
    sourceCanvas.width = left.width; sourceCanvas.height = left.height;
    const sourceContext = sourceCanvas.getContext('2d');
    if (!sourceContext) return {available: false, exact: false, reason: 'source context unavailable'};
    sourceContext.drawImage(left, 0, 0);
    const sourceComparison = compare(sourceContext, expectedSource, left.width, left.height);
    if (!sourceComparison.exact) {
      return {available: sourceComparison.available === true, exact: false,
        dimensions_equal: sourceComparison.dimensions_equal === true,
        source: sourceComparison,
        intermediate: {available: false, exact: false, reason: 'source mismatch'},
        final: {available: false, exact: false, reason: 'source mismatch'}};
    }
    const bCanvas = document.createElement('canvas');
    window.__bookwalkerMarkInternalCanvas?.(bCanvas);
    bCanvas.width = intermediateWidth; bCanvas.height = intermediateHeight;
    const bContext = bCanvas.getContext('2d');
    if (!bContext) return {available: false, exact: false, reason: 'intermediate context unavailable'};
    bContext.imageSmoothingEnabled = copySmoothingEnabled;
    bContext.imageSmoothingQuality = copySmoothingQuality;
    bContext.drawImage(sourceCanvas,
      Number(copySourceRect.x), Number(copySourceRect.y), Number(copySourceRect.width), Number(copySourceRect.height),
      Number(copyDestination.x), Number(copyDestination.y), Number(copyDestination.width), Number(copyDestination.height));
    const intermediateComparison = compare(bContext, expectedIntermediate, intermediateWidth, intermediateHeight);
    if (!intermediateComparison.exact) {
      return {available: intermediateComparison.available === true, exact: false,
        dimensions_equal: intermediateComparison.dimensions_equal === true,
        source: sourceComparison,
        intermediate: intermediateComparison,
        final: {available: false, exact: false, reason: 'intermediate mismatch'}};
    }
    const finalWidth = Number(finalDestination.width);
    const finalHeight = Number(finalDestination.height);
    if (!Number.isInteger(finalWidth) || !Number.isInteger(finalHeight)
        || finalWidth <= 0 || finalHeight <= 0) {
      return {available: false, exact: false, reason: 'final destination dimensions unavailable'};
    }
    const finalCanvasWidth = Number(finalCanvasDimensions?.width);
    const finalCanvasHeight = Number(finalCanvasDimensions?.height);
    const finalX = Number(finalDestination.x);
    const finalY = Number(finalDestination.y);
    if (!Number.isInteger(finalCanvasWidth) || !Number.isInteger(finalCanvasHeight)
        || finalCanvasWidth <= 0 || finalCanvasHeight <= 0
        || !Number.isInteger(finalX) || !Number.isInteger(finalY)
        || finalX < 0 || finalY < 0
        || finalX + finalWidth > finalCanvasWidth || finalY + finalHeight > finalCanvasHeight) {
      return {available: false, exact: false, reason: 'final replay canvas geometry unavailable'};
    }
    const finalCanvas = document.createElement('canvas');
    window.__bookwalkerMarkInternalCanvas?.(finalCanvas);
    finalCanvas.width = finalCanvasWidth; finalCanvas.height = finalCanvasHeight;
    const finalContext = finalCanvas.getContext('2d');
    if (!finalContext) return {available: false, exact: false, reason: 'final context unavailable'};
    finalContext.imageSmoothingEnabled = finalSmoothingEnabled;
    finalContext.imageSmoothingQuality = finalSmoothingQuality;
    finalContext.drawImage(bCanvas,
      Number(finalSourceRect.x), Number(finalSourceRect.y), Number(finalSourceRect.width), Number(finalSourceRect.height),
      finalX, finalY, finalWidth, finalHeight);
    const finalComparison = compare(finalContext, expectedFinal, finalWidth, finalHeight, finalX, finalY);
    return {available: Boolean(sourceComparison.available && intermediateComparison.available && finalComparison.available),
      dimensions_equal: Boolean(sourceComparison.dimensions_equal && intermediateComparison.dimensions_equal && finalComparison.dimensions_equal),
      exact: Boolean(sourceComparison.exact && intermediateComparison.exact && finalComparison.exact),
      source: sourceComparison, intermediate: intermediateComparison, final: finalComparison};
  } finally {
    left.close(); expectedSource.close(); expectedIntermediate.close(); expectedFinal.close();
  }
}
"""

_CAMPAIGN_TAG = re.compile(r"【[^】]*】")
_TRAILING_VOLUME = re.compile(r"^(?P<title>.+?)(?:\s*第\s*)?(?P<number>\d+)\s*巻?$")
_SERIES_COUNT = re.compile(r"[（(]\s*(\d+)\s*冊[）)]")


def clean_bookwalker_title(raw_title: str | None) -> str:
    """Remove BookWalker's campaign labels from a product title."""

    normalized = " ".join((raw_title or "").split())
    return _CAMPAIGN_TAG.sub("", normalized).strip()


def split_bookwalker_title(
    raw_title: str | None,
    *,
    series_count: int | None = None,
) -> tuple[str, str | None]:
    """Return a clean title and a BOOK_NAMING_RULES-compatible volume label."""

    cleaned = clean_bookwalker_title(raw_title)
    match = _TRAILING_VOLUME.match(cleaned)
    if not match or not match.group("title").strip():
        return cleaned, None
    title = match.group("title").strip()
    number = int(match.group("number"))
    width = 3 if number >= 100 or (series_count is not None and series_count >= 100) else 2
    return title, f"第{number:0{width}d}巻"


def is_last_page_counter(text: str) -> bool:
    """Return whether a viewer counter has reached its final page."""

    match = re.search(r"(\d+)\s*/\s*(\d+)", " ".join(text.split()))
    return bool(match and match.group(1) == match.group(2))


def _capture_from_data_url(value: object) -> CaptureResult:
    if not isinstance(value, str) or not value.startswith("data:image/png;base64,"):
        raise CaptureUnavailableError("BookWalker native source PNG is unavailable")
    try:
        data = base64.b64decode(value.split(",", 1)[1], validate=True)
        return capture_png_bytes(data)
    except (ValueError, TypeError, BinasciiError) as exc:
        raise CaptureUnavailableError(
            "BookWalker native source PNG could not be decoded"
        ) from exc


def parse_bookwalker_lossless_jpeg_output(value: str | None) -> bool:
    """Parse the BookWalker-local reconstructed-JPEG output switch.

    The P3 default is enabled when the environment variable is unset. An
    explicit value must be one of the documented on/off spellings so a typo
    cannot silently change the capture format.
    """

    if value is None:
        return True
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(
        "BOOKWALKER_LOSSLESS_JPEG_OUTPUT must be one of: "
        "0, 1, false, true, no, yes, off, on"
    )


def parse_bookwalker_final_pixel_verify(value: str | None) -> bool:
    """Parse the opt-in final reconstructed-JPEG pixel verification switch."""

    if value is None:
        return False
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(
        "BOOKWALKER_FINAL_PIXEL_VERIFY must be one of: "
        "0, 1, false, true, no, yes, off, on"
    )


def _elapsed_ms(start: float) -> float:
    return round((time.perf_counter() - start) * 1000, 2)


def _part_timing_defaults() -> dict[str, float]:
    return {
        "mapping_analysis_ms": 0.0,
        "imagebitmap_signature_ms": 0.0,
        "candidate_signature_ms_total": 0.0,
        "raw_full_resolution_compare_ms": 0.0,
        "lossless_reconstruction_ms": 0.0,
        "final_browser_pixel_compare_ms": 0.0,
    }


def _capture_timing_defaults() -> dict[str, float]:
    return {
        "native_materialization_ms": 0.0,
        "original_jpeg_match_ms": 0.0,
        "original_native_signature_ms": 0.0,
        "original_candidate_signature_ms": 0.0,
        "original_match_scan_ms": 0.0,
        "original_retry_wait_ms": 0.0,
        "original_total_ms": 0.0,
        "direct_original_jpeg_ms": 0.0,
        "lossless_evaluation_total_ms": 0.0,
        "capture_total_ms": 0.0,
        "capture_unaccounted_ms": 0.0,
    }


def _original_match_debug_defaults() -> dict[str, int]:
    return {
        "original_attempt_count": 0,
        "original_retry_wait_count": 0,
        "original_pending_task_count_at_start": 0,
        "original_candidate_count_at_start": 0,
        "original_candidate_count_at_end": 0,
        "original_candidate_generation_start": 0,
        "original_candidate_generation_end": 0,
    }


def _evaluation_timing_defaults() -> dict[str, float]:
    return {
        "evaluation_total": 0.0,
        "selected_trace_fetch_ms": 0.0,
        "upstream_trace_fetch_ms": 0.0,
        "trace_fetch_ms": 0.0,
        "selected_trace_decode_ms": 0.0,
        "upstream_trace_decode_ms": 0.0,
        "trace_decode_ms": 0.0,
        "trace_python_analysis_ms": 0.0,
        "mapping_analysis": 0.0,
        "imagebitmap_signature": 0.0,
        "candidate_signature_total": 0.0,
        "raw_full_resolution_compare": 0.0,
        "lossless_reconstruction": 0.0,
        "final_browser_pixel_compare": 0.0,
        "measured_component_total_ms": 0.0,
        "unaccounted_ms": 0.0,
    }


def _trace_payload_stats(trace: object) -> dict[str, int]:
    stats = {
        "trace_completed_mapping_count": 0,
        "trace_completed_tile_record_count": 0,
        "trace_active_segment_count": 0,
        "trace_active_tile_record_count": 0,
        "trace_dropped_completed_mapping_count": 0,
        "trace_dropped_active_segment_count": 0,
        "trace_requested_mapping_count": 0,
        "trace_returned_mapping_count": 0,
        "trace_returned_tile_record_count": 0,
        "trace_missing_mapping_count": 0,
        "trace_compact_source_table_count": 0,
        "trace_compact_target_table_count": 0,
        "trace_compact_transform_table_count": 0,
        "trace_compact_composite_table_count": 0,
        "trace_compact_filter_table_count": 0,
    }
    if not isinstance(trace, dict):
        return stats

    completed = trace.get("completedMappings", trace.get("completed_mappings"))
    retained_stats = {
        "trace_completed_mapping_count": (
            "retainedCompletedMappingCount",
            "retained_completed_mapping_count",
        ),
        "trace_completed_tile_record_count": (
            "retainedCompletedTileRecordCount",
            "retained_completed_tile_record_count",
        ),
        "trace_active_segment_count": (
            "activeSegmentCount",
            "active_segment_count",
        ),
        "trace_active_tile_record_count": (
            "activeTileRecordCount",
            "active_tile_record_count",
        ),
        "trace_requested_mapping_count": (
            "requestedMappingCount",
            "requested_mapping_count",
        ),
        "trace_returned_mapping_count": (
            "returnedCompletedMappingCount",
            "returned_mapping_count",
        ),
        "trace_returned_tile_record_count": (
            "returnedTileRecordCount",
            "returned_tile_record_count",
        ),
        "trace_missing_mapping_count": (
            "missingMappingCount",
            "missing_mapping_count",
        ),
        "trace_compact_source_table_count": (
            "compactSourceTableCount",
            "compact_source_table_count",
        ),
        "trace_compact_target_table_count": (
            "compactTargetTableCount",
            "compact_target_table_count",
        ),
        "trace_compact_transform_table_count": (
            "compactTransformTableCount",
            "compact_transform_table_count",
        ),
        "trace_compact_composite_table_count": (
            "compactCompositeTableCount",
            "compact_composite_table_count",
        ),
        "trace_compact_filter_table_count": (
            "compactFilterTableCount",
            "compact_filter_table_count",
        ),
    }
    has_retained_summary = any(
        key in trace
        for key in (
            "retainedCompletedMappingCount",
            "retained_completed_mapping_count",
        )
    )
    if has_retained_summary:
        for stat_name, keys in retained_stats.items():
            for key in keys:
                if key not in trace:
                    continue
                try:
                    stats[stat_name] = int(trace[key])
                except (TypeError, ValueError):
                    pass
                break
    else:
        if isinstance(completed, list):
            stats["trace_completed_mapping_count"] = len(completed)
            for mapping in completed:
                if not isinstance(mapping, dict):
                    continue
                tiles = mapping.get("tileDraws", mapping.get("tile_draws"))
                if isinstance(tiles, list):
                    stats["trace_completed_tile_record_count"] += len(tiles)

        active = trace.get("activeSegments", trace.get("active_segments"))
        if isinstance(active, dict):
            stats["trace_active_segment_count"] = len(active)
            for segment in active.values():
                if not isinstance(segment, dict):
                    continue
                tiles = segment.get("tileDraws", segment.get("tile_draws"))
                if isinstance(tiles, list):
                    stats["trace_active_tile_record_count"] += len(tiles)

    for key in (
        "droppedCompletedMappingCount",
        "dropped_completed_mapping_count",
    ):
        if key in trace:
            try:
                stats["trace_dropped_completed_mapping_count"] = int(trace[key])
            except (TypeError, ValueError):
                pass
            break
    for key in (
        "droppedActiveSegmentCount",
        "dropped_active_segment_count",
    ):
        if key in trace:
            try:
                stats["trace_dropped_active_segment_count"] = int(trace[key])
            except (TypeError, ValueError):
                pass
            break
    return stats


def _native_call_is_safe(call: dict[str, Any]) -> bool:
    source = call.get("source")
    if not isinstance(source, dict) or source.get("constructor") not in {
        "ImageBitmap",
        # The purchased full viewer decodes its JPEG tiles into a canvas
        # before drawing them to the renderer canvas. The same geometry,
        # transform, composition, and exact JPEG signature checks still apply.
        "HTMLCanvasElement",
    }:
        return False
    if (
        source.get("constructor") == "HTMLCanvasElement"
        and not call.get("snapshotId")
    ):
        return False
    transform = call.get("transform")
    if not isinstance(transform, dict):
        return False
    if any(
        transform.get(key) != expected
        for key, expected in {
            "a": 1,
            "b": 0,
            "c": 0,
            "d": 1,
            "e": 0,
            "f": 0,
        }.items()
    ):
        return False
    return (
        call.get("globalAlpha", 1) in (1, 1.0)
        and
        call.get("globalCompositeOperation") == "source-over"
        and call.get("filter") == "none"
        and call.get("snapshotError") in (None, "")
    )


def _initial_proof_ready_for_redraw(part: object) -> bool:
    """Check immutable proof stages before a bounded same-source redraw."""

    if not isinstance(part, dict):
        return False
    required_flags = (
        "mapping_proven",
        "raw_jpeg_exact",
        "coefficient_exact",
        "component_quantization_selectors_equal",
        "native_pixel_exact",
    )
    comparison = part.get("cropped_chain_pixel_comparison")
    stages_exact = (
        isinstance(comparison, dict)
        and comparison.get("available") is True
        and comparison.get("dimensions_equal") is True
        and comparison.get("exact") is True
        and all(
            isinstance(comparison.get(stage), dict)
            and comparison[stage].get("available") is True
            and comparison[stage].get("dimensions_equal") is True
            and comparison[stage].get("exact") is True
            and comparison[stage].get("differing_pixel_count") == 0
            and comparison[stage].get("max_channel_difference") == 0
            for stage in ("source", "intermediate", "final")
        )
    )
    return (
        part.get("candidate_count_full_exact") == 1
        and part.get("strict_mcu_aligned") is True
        and part.get("quantization_tables_equal") is True
        and all(part.get(flag) is True for flag in required_flags)
        and stages_exact
    )


def _p4b_stable_current_fallback_authority(proof: object) -> bool:
    """Require a live, unchanged anchor before retaining a strict PNG fallback."""

    if not isinstance(proof, dict) or proof.get("available") is not True:
        return False
    before = proof.get("before")
    after = proof.get("after")
    current = proof.get("current")
    if not isinstance(before, dict) or not isinstance(after, dict):
        return False
    if (
        not isinstance(current, dict)
        or current.get("available") is not True
        or current.get("dimensions_equal") is not True
        or current.get("exact") is not True
        or current.get("differing_pixel_count") != 0
        or current.get("max_channel_difference") != 0
    ):
        return False
    required = (
        "traceId", "actualCanvasId", "bookIdentity", "counter",
        "geometryToken", "traceEpoch", "geometryVersion", "resetEpoch",
        "canvasWidth", "canvasHeight", "targetContentVersion",
    )
    for anchor in (before, after):
        if any(anchor.get(field) in (None, "") for field in required):
            return False
        if (
            anchor.get("connected") is not True
            or anchor.get("geometryHistoryIncomplete") is not False
            or anchor.get("unknownMutation") is not False
            or anchor.get("observerAvailable") is not True
            or anchor.get("observerTakeRecordsAvailable") is not True
            or anchor.get("observerFlushed") is not True
        ):
            return False
        selected = anchor.get("selected")
        if not isinstance(selected, dict) or any(
            selected.get(field) in (None, "")
            for field in (
                "canvasId", "operationIndex", "sourceId", "sourceCanvasId",
                "traceEpoch", "sourceRect", "destination",
                "sourceContentVersion", "fullSourceSnapshotId",
                "targetSnapshotId", "targetContentVersionAfter",
            )
        ):
            return False
        if (
            selected.get("canvasId") != anchor.get("actualCanvasId")
            or selected.get("traceEpoch") != anchor.get("traceEpoch")
        ):
            return False
    return before == after


class BookWalkerStrictEntryError(RuntimeError):
    """Raised when a strict BookWalker entry cannot be proved safe."""

    def __init__(
        self,
        *,
        strategy: AccessStrategy,
        expected_kind: ReaderControlKind,
        observed_kinds: list[ReaderControlKind],
        reason: str,
    ) -> None:
        self.strategy = strategy
        self.expected_kind = expected_kind
        self.observed_kinds = tuple(observed_kinds)
        self.reason = reason
        observed = ", ".join(
            dict.fromkeys(kind.value for kind in observed_kinds)
        ) or "none"
        super().__init__(
            "BookWalker strict entry failed: "
            f"strategy={strategy!r}, expected kind={expected_kind.value!r}, "
            f"observed kinds={observed}; reason={reason}"
        )


@dataclass(slots=True)
class LosslessReconstructionEvaluation:
    """Debug proof plus verified reconstructed captures for one visible spread."""

    debug: dict[str, Any]
    captures: tuple[CaptureResult, ...] | None

    def __getitem__(self, key: str) -> Any:
        """Keep the old debug-only indexing convenient for local diagnostics."""

        return self.debug[key]


class BookWalkerAdapter(SiteAdapter):
    """Canvas viewer adapter for one BookWalker content ID."""

    # These are decoded RGBA hashes of the native artifacts observed for the
    # terminal BookWalker notice/logo screens.  They identify policy-known AD
    # artifacts; they are not source fixtures and are never used without the
    # terminal counter role and a single native draw proof.
    _known_terminal_native_artifacts: ClassVar[dict[tuple[int, int, str], str]] = {
        (960, 1280, "f20c0701d0333b77bc99d092849846c1bd1ad28dbfc3481bf69d4e0f4cd1ccb5"): "notice",
        (1443, 2048, "fd87c452a40a1049339b4dc31e62914c2a58d290a569d9b1d1bc07d37974b6af"): "logo",
        (1443, 2048, "d51b8376a7895636d98c346ad6191a592f7ad68bc77af90e8331c5e536af4889"): "logo",
        (1443, 2048, "e42a47424da6fb7c30fd33f5f33c67d638385b069c2a291143e977028df02f78"): "logo",
    }
    # Verified native-fallback crop variants.  The crop signature is part of
    # the key so a hash cannot be reused across a different source rectangle
    # or output shape.  These entries are policy data, not image fixtures.
    _known_terminal_native_crop_artifacts: ClassVar[
        dict[tuple[str, tuple[int, int], tuple[float, float, float, float], tuple[int, int], str], str]
    ] = {
        (
            "logo",
            (722, 1024),
            (0.0, 0.0, 721.5, 1024.0),
            (722, 1024),
            "28413cad8746077e0c9cb0abca5a4311778847ff1353a5239d0d86be4f68542b",
        ): "logo",
        (
            "logo",
            (722, 1024),
            (0.0, 0.0, 721.5, 1024.0),
            (722, 1024),
            "f231fbafc36022177876cd4a68eda515cd57865fdd3ce0f381e2714b639ceb20",
        ): "logo",
    }
    _diagnostic_max_records = 256
    _diagnostic_max_bytes = 4 * 1024 * 1024

    # Use deferred source-native capture followed by conservative JPEG
    # matching in production. A failed match still returns the native PNG.
    enable_original_jpeg_capture = True
    page_change_timeout_ms = 14_000
    initialize_timeout_ms = 45_000
    navigation_wait_timeout_ms = 5_000
    strict_entry_destination_poll_interval_ms = 100
    read_link_wait_timeout_ms = 5_000
    strict_entry_initial_settle_ms = 250
    strict_candidate_poll_interval_ms = 100
    strict_candidate_stability_samples = 2
    render_stable_checks = 4
    advance_retry_count = 6
    advance_retry_interval_ms = 2_000
    end_marker_grace_ms = 1_500
    spread_ratio = 1.25
    original_capture_attempts = 3
    original_capture_retry_interval_ms = 150
    original_response_task_limit = 8
    original_response_route_patterns = (
        "**://viewer-epubs*.bookwalker.jp/**",
        "**://bw-bv-epubs.bookwalker.jp/**",
    )
    _strict_scope_selectors = (
        "#js-read-check-book-cover-main-button",
        "#js-read-check",
        "#js-subscription-check",
    )
    _strict_control_selector = (
        'a, button, [role="button"], [data-action-label]'
    )

    def __init__(
        self,
        *,
        auto_login_email: str | None = None,
        auto_login_password: str | None = None,
    ) -> None:
        self.capture_mode = os.environ.get("BOOKWALKER_CAPTURE_MODE", "native").strip().lower()
        if self.capture_mode not in {"native", "canvas"}:
            raise ValueError(
                "BOOKWALKER_CAPTURE_MODE must be 'native' or 'canvas', "
                f"got {self.capture_mode!r}"
            )
        self.lossless_jpeg_output_enabled = parse_bookwalker_lossless_jpeg_output(
            os.environ.get("BOOKWALKER_LOSSLESS_JPEG_OUTPUT")
        )
        self.final_pixel_verify_enabled = parse_bookwalker_final_pixel_verify(
            os.environ.get("BOOKWALKER_FINAL_PIXEL_VERIFY")
        )
        self._access_strategy: AccessStrategy = "auto"
        self._auto_login_email = auto_login_email
        self._auto_login_password = auto_login_password
        self._auto_login_attempted = False
        self._initial_content_id: str | None = None
        self._capture_run = 0
        self._output_title: str | None = None
        self._output_author: str | None = None
        self._output_volume: str | None = None
        self._output_genre = "小説"
        self._series_count: int | None = None
        self._final_navigation_pending = False
        self._diagnostics_dir: Path | None = None
        self._diagnostics_run_id = uuid4().hex
        self._diagnostics_records = 0
        self._diagnostics_omitted_successes = 0
        self._diagnostics_path: Path | None = None
        self._last_terminal_diagnostic_key: tuple[object, ...] | None = None
        self._last_terminal_artifact_failure: dict[str, Any] | None = None
        # Internal, non-persisted anchor join state.  Diagnostic sanitization
        # intentionally redacts opaque token fields, so retry authority must
        # not be reconstructed from the JSON-safe failure projection.
        self._terminal_reinspection_anchor_state: dict[str, Any] | None = None
        self._terminal_reinspection_raw_success_anchor: dict[str, Any] | None = None
        # P4B atomic proof is activated per capture only after the strict
        # executed-clear provenance predicate succeeds.  The separate
        # diagnostic flag remains available for isolated proof fixtures.
        self._diagnostic_p4b_atomic_proof = False
        self._p4b_atomic_proof_active = False
        self._p4b_redraw_attempted = False
        self._p4b_redraw_native_captures: tuple[CaptureResult, ...] | None = None
        self._p4b_redraw_selected_draw_calls: list[dict[str, Any]] | None = None
        self._terminal_skip_identity: ContentIdentity | None = None
        self._original_candidates = OriginalJpegCache()
        self._original_response_tasks: set[asyncio.Task[None]] = set()
        self._original_candidate_generation = 0
        self._original_candidate_event = asyncio.Event()
        self._original_response_sequence = 0
        self._original_response_page: Page | None = None
        self._original_capture_decisions: dict[
            tuple[tuple[int | None, int | None, str], ...],
            tuple[str, ...] | None,
        ] = {}
        self._original_capture_negative_generations: dict[
            tuple[tuple[int | None, int | None, str], ...],
            int,
        ] = {}
        self._capture_debug: dict[str, Any] = {
            "bookwalker_capture": {
                "returned_path": "rendered_canvas",
                "timing_ms": _capture_timing_defaults(),
                "original_match": _original_match_debug_defaults(),
                "lossless_shadow": {
                    "attempted": False,
                    "spread_ready": False,
                    "output_enabled": self.lossless_jpeg_output_enabled,
                    "output_used": False,
                    "final_pixel_verify_enabled": self.final_pixel_verify_enabled,
                    "final_pixel_compare_performed": False,
                    "parts": [],
                },
            }
        }

    def get_access_profile(self) -> AccessProfile:
        return bookwalker_access_profile()

    async def configure_run(
        self, page: Page, access_strategy: AccessStrategy
    ) -> None:
        """Store BookWalker's access intent before the runner navigates."""

        del page
        if access_strategy not in {"auto", "direct", "quota"}:
            raise UnsupportedAccessStrategyError(
                f"BookWalkerAdapter does not support "
                f"access_strategy={access_strategy!r}"
            )
        self._access_strategy = access_strategy
        self._auto_login_attempted = False
        diagnostics_root = Path(
            os.environ.get(
                "BOOKWALKER_DIAGNOSTICS_DIR", "output/diagnostics/bookwalker"
            )
        )
        self._diagnostics_dir = diagnostics_root
        self._diagnostics_run_id = uuid4().hex
        self._diagnostics_path = diagnostics_root / (
            f"run-{self._diagnostics_run_id}.jsonl"
        )
        self._last_terminal_artifact_failure = None
        self._terminal_reinspection_anchor_state = None
        self._terminal_reinspection_raw_success_anchor = None
        self._diagnostics_records = 0
        self._diagnostics_omitted_successes = 0
        self._last_terminal_diagnostic_key = None
        self._terminal_skip_identity = None

    def _append_diagnostic(self, record: dict[str, Any]) -> None:
        """Best-effort bounded JSONL diagnostics; never affect capture state."""

        path = self._diagnostics_path
        if path is None or self._diagnostics_records >= self._diagnostic_max_records:
            return
        try:
            sanitized = self._safe_diagnostic_value(record)
            if not isinstance(sanitized, dict):
                return
            payload = {
                "schema": "bookwalker.capture-diagnostic.v1",
                "run_id": self._diagnostics_run_id,
                **sanitized,
            }
            encoded = (
                json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
                + "\n"
            ).encode("utf-8")
            if len(encoded) > 128 * 1024:
                return
            if path.exists() and path.stat().st_size + len(encoded) > self._diagnostic_max_bytes:
                return
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("ab") as stream:
                stream.write(encoded)
            self._diagnostics_records += 1
        except (OSError, TypeError, ValueError):
            # Diagnostics are deliberately non-authoritative and must not
            # change the source-native capture result.
            return

    @staticmethod
    def _safe_diagnostic_value(value: object) -> object:
        if isinstance(value, str):
            lowered = value.casefold().strip()
            if (
                "://" in value
                or "?" in value
                or "&" in value
                or lowered.startswith(("data:", "blob:", "bearer "))
                or any(
                    marker in lowered
                    for marker in (
                        "authorization:",
                        "password=",
                        "credential=",
                        "signature=",
                        "signed",
                        "access_token=",
                    )
                )
            ):
                return "<redacted>"
            return value[:512]
        if isinstance(value, (int, float, bool)) or value is None:
            return value
        if isinstance(value, dict):
            return {
                str(key): BookWalkerAdapter._safe_diagnostic_value(item)
                for key, item in value.items()
                if not any(
                    marker in str(key).lower()
                    for marker in (
                        "url", "header", "cookie", "body", "data", "token",
                        "secret", "password", "authorization", "credential",
                        "signature", "query", "bearer",
                    )
                )
            }
        if isinstance(value, (list, tuple)):
            return [BookWalkerAdapter._safe_diagnostic_value(item) for item in value]
        return "<unsupported>"

    async def _read_page_counter_pair(
        self, page: Page
    ) -> tuple[int | None, int | None, str | None]:
        try:
            raw = await page.locator("#pageSliderCounter").inner_text(timeout=1000)
        except (AttributeError, PlaywrightError, PlaywrightTimeoutError, TimeoutError):
            return None, None, None
        normalized = " ".join(raw.split())
        match = re.fullmatch(r"(\d+)\s*/\s*(\d+)", normalized)
        if match is None:
            return None, None, normalized or None
        return int(match.group(1)), int(match.group(2)), normalized

    async def _native_terminal_artifact(
        self, page: Page, canvas: Locator
    ) -> dict[str, Any] | None:
        """Read the current native draw using the normal selected-call shape.

        This helper is intentionally non-consuming: it does not arm, clear,
        reset, or call capture_page. If the same selected native call cannot
        be materialized safely, the terminal image remains CONTENT.
        """

        self._last_terminal_artifact_failure = {
            "stage": "unknown",
            "reason": "native artifact inspection did not complete",
        }
        self._terminal_reinspection_anchor_state = None
        self._terminal_reinspection_raw_success_anchor = None

        def reject(stage: str, reason: str, **details: object) -> None:
            failure: dict[str, Any] = {"stage": stage, "reason": reason}
            for key, value in details.items():
                failure[key] = self._safe_diagnostic_value(value)
            self._last_terminal_artifact_failure = failure

        try:
            trace_id = await canvas.get_attribute("data-bookwalker-trace-id")
            size = await canvas.evaluate(
                "element => ({width: element.width, height: element.height})"
            )
            if not trace_id or not isinstance(size, dict):
                reject("geometry", "trace id or canvas size unavailable")
                return None
            width = int(size["width"])
            height = int(size["height"])
            initial_anchor = await canvas.evaluate(
                _BOOKWALKER_NATIVE_ANCHOR_SCRIPT, None
            )
            if not isinstance(initial_anchor, dict):
                reject("anchor", "initial anchor unavailable")
                return None
            draw_calls = await page.evaluate(
                """
                traceId => (window.__bookwalkerNativeDrawCalls || [])
                  .filter(call => call.canvasId === traceId)
                """,
                trace_id,
            )
            diagnostic_draw_calls = [
                {
                    "canvasId": call.get("canvasId"),
                    "sourceId": call.get("sourceId"),
                    "sourceCanvasId": call.get("sourceCanvasId"),
                    "traceOperationIndex": call.get("traceOperationIndex"),
                    "traceEpoch": call.get("traceEpoch"),
                    "targetResetEpoch": call.get("targetResetEpoch"),
                    "sourceContentVersion": call.get("sourceContentVersion"),
                    "targetContentVersionAfter": call.get("targetContentVersionAfter"),
                    "sourceRect": call.get("sourceRect"),
                    "destination": call.get("destination"),
                    "sourceDimensions": (
                        {
                            "width": call["source"].get("width"),
                            "height": call["source"].get("height"),
                        }
                        if isinstance(call.get("source"), dict)
                        else None
                    ),
                }
                for call in draw_calls
                if isinstance(call, dict)
            ]
            boxes = await self._page_draw_rectangles(page, canvas)
            if len(boxes) != 1:
                geometry_rows = await page.evaluate(
                    """
                    traceId => {
                      const rows = (window.__bookwalkerDrawCalls || [])
                        .filter(call => call.canvasId === traceId)
                        .map(call => ({
                        canvasId: call.canvasId,
                        operationIndex: call.operationIndex,
                        traceEpoch: call.traceEpoch,
                        resetEpoch: call.resetEpoch,
                        destination: call.destination,
                        }));
                      const limit = 32;
                      if (rows.length <= limit) {
                        return {total: rows.length, omitted: 0, rows};
                      }
                      const head = rows.slice(0, limit / 2);
                      const tail = rows.slice(-limit / 2);
                      return {
                        total: rows.length,
                        omitted: rows.length - limit,
                        rows: [...head, ...tail],
                      };
                    }
                    """,
                    trace_id,
                )
                reject(
                    "geometry",
                    "expected one page draw rectangle",
                    box_count=len(boxes),
                    boxes=boxes,
                    native_calls=diagnostic_draw_calls,
                    geometry_rows=geometry_rows,
                    counter=initial_anchor.get("counter"),
                    canvas_id=trace_id,
                )
                return None
            selected = select_native_draw_calls(
                draw_calls,
                canvas_id=trace_id,
                canvas_width=width,
                canvas_height=height,
                boxes=boxes,
            )
            if selected is None or len(selected) != 1:
                reject(
                    "selection",
                    "native selector returned no unique call",
                    draw_call_count=len(draw_calls),
                    selected_count=0 if selected is None else len(selected),
                )
                return None
            selected_call = selected[0]
            if not _native_call_is_safe(selected_call):
                reject("safety", "selected native call failed safety gate")
                return None
            operation_index = selected_call.get("traceOperationIndex")
            if not isinstance(operation_index, int):
                reject("selection", "selected operation index unavailable")
                return None
            before = await canvas.evaluate(
                _BOOKWALKER_NATIVE_ANCHOR_SCRIPT, operation_index
            )
            if not isinstance(before, dict) or before.get("selected") is None:
                reject("anchor", "selected call missing from before anchor")
                return None
            source = selected_call.get("source")
            source_rect = selected_call.get("sourceRect")
            if not isinstance(source, dict) or not isinstance(source_rect, dict):
                reject("source_bounds", "source or source rectangle unavailable")
                return None
            source_width = float(source.get("width", 0))
            source_height = float(source.get("height", 0))
            source_x = float(source_rect.get("x", -1))
            source_y = float(source_rect.get("y", -1))
            source_rect_width = float(source_rect.get("width", 0))
            source_rect_height = float(source_rect.get("height", 0))
            if not all(
                math.isfinite(value)
                for value in (
                    source_width,
                    source_height,
                    source_x,
                    source_y,
                    source_rect_width,
                    source_rect_height,
                )
            ):
                reject("source_bounds", "source geometry is non-finite")
                return None
            full_source_rect = (
                source_width <= 0
                or source_height <= 0
                or source_x < 0
                or source_y < 0
                or source_rect_width <= 0
                or source_rect_height <= 0
                or source_x + source_rect_width > source_width
                or source_y + source_rect_height > source_height
                or source_x != 0
                or source_y != 0
                or source_rect_width != source_width
                or source_rect_height != source_height
            ) is False
            crop_variant = (
                source.get("constructor") == "HTMLCanvasElement"
                and (round(source_width), round(source_height)) == (722, 1024)
                and source_x == 0
                and source_y == 0
                and source_rect_width == 721.5
                and source_rect_height == 1024
            )
            if not full_source_rect and not crop_variant:
                reject(
                    "source_bounds",
                    "source rectangle is neither full-frame nor verified crop",
                    source_dimensions=(source_width, source_height),
                    source_rect=(source_x, source_y, source_rect_width, source_rect_height),
                )
                return None
            materialized = await self._materialize_native_source_crops(page, selected)
            if len(materialized) != 1:
                reject("materialize", "native source materialization was not unique", count=len(materialized))
                return None
            materialized_call = materialized[0]
            source_png = materialized_call.get("sourceCropPng")
            if not source_png:
                reject("materialize", "native source crop was unavailable")
                return None
            source_capture = _capture_from_data_url(source_png)
            if (source_capture.width, source_capture.height) != (
                round(source_rect_width),
                round(source_rect_height),
            ):
                reject(
                    "materialize",
                    "materialized crop dimensions mismatch",
                    actual_dimensions=(source_capture.width, source_capture.height),
                    expected_dimensions=(round(source_rect_width), round(source_rect_height)),
                )
                return None
            decoded = await page.evaluate(
                _BOOKWALKER_NATIVE_RGBA_HASH_SCRIPT, source_png
            )
            after = await canvas.evaluate(
                _BOOKWALKER_NATIVE_ANCHOR_SCRIPT, operation_index
            )
            if (
                not isinstance(after, dict)
                or after.get("selected") is None
                or operation_index not in after.get("operationIndices", [])
            ):
                reject("anchor", "selected call missing or changed after materialization")
                return None
            required_anchor_fields = (
                "bookIdentity",
                "counter",
                "actualCanvasId",
                "connected",
                "targetContentVersion",
                "geometryToken",
                "geometryVersion",
            )

            def anchor_summary(anchor: object) -> dict[str, Any] | None:
                if not isinstance(anchor, dict):
                    return None
                summary: dict[str, Any] = {
                    field: self._safe_diagnostic_value(anchor.get(field))
                    for field in (
                        "bookIdentity",
                        "counter",
                        "traceId",
                        "actualCanvasId",
                        "connected",
                        "targetContentVersion",
                        "geometryToken",
                        "geometryVersion",
                        "geometryHistoryIncomplete",
                    )
                }
                selected = anchor.get("selected")
                if isinstance(selected, dict):
                    summary["selected"] = {
                        field: self._safe_diagnostic_value(selected.get(field))
                        for field in (
                            "canvasId",
                            "operationIndex",
                            "sourceId",
                            "sourceCanvasId",
                            "snapshotId",
                            "fullSourceSnapshotId",
                            "targetSnapshotId",
                            "sourceContentVersion",
                            "targetContentVersionAfter",
                        )
                    }
                return summary

            anchors = (initial_anchor, before, after)
            for anchor in anchors:
                if any(anchor.get(field) in (None, "") for field in required_anchor_fields):
                    reject("anchor", "required anchor field unavailable")
                    return None
                if anchor.get("connected") is not True:
                    reject("anchor", "target canvas is disconnected")
                    return None
                if anchor.get("actualCanvasId") != trace_id:
                    reject("anchor", "actual canvas identity changed")
                    return None
                if (
                    self._initial_content_id is not None
                    and anchor.get("bookIdentity") != self._initial_content_id
                ):
                    reject("anchor", "book identity changed")
                    return None
            for field in required_anchor_fields:
                if not (initial_anchor.get(field) == before.get(field) == after.get(field)):
                    self._terminal_reinspection_anchor_state = {
                        "field": field,
                        "initial_anchor": {
                            key: initial_anchor.get(key)
                            for key in (
                                "traceId",
                                *required_anchor_fields,
                                "geometryHistoryIncomplete",
                            )
                        },
                        "anchor_before": {
                            key: before.get(key)
                            for key in (
                                "traceId",
                                *required_anchor_fields,
                                "geometryHistoryIncomplete",
                            )
                        },
                        "anchor_after": {
                            key: after.get(key)
                            for key in (
                                "traceId",
                                *required_anchor_fields,
                                "geometryHistoryIncomplete",
                            )
                        },
                        "history_incomplete_before": before.get(
                            "geometryHistoryIncomplete"
                        ),
                        "history_incomplete_after": after.get(
                            "geometryHistoryIncomplete"
                        ),
                    }
                    reject(
                        "anchor",
                        "anchor field changed during inspection",
                        field=field,
                        initial_anchor=anchor_summary(initial_anchor),
                        anchor_before=anchor_summary(before),
                        anchor_after=anchor_summary(after),
                        history_incomplete_before=before.get("geometryHistoryIncomplete"),
                        history_incomplete_after=after.get("geometryHistoryIncomplete"),
                    )
                    return None
            selected_before = before.get("selected")
            selected_after = after.get("selected")
            if not isinstance(selected_before, dict) or not isinstance(selected_after, dict):
                reject("anchor", "selected snapshot unavailable")
                return None
            if selected_before != selected_after:
                reject("anchor", "selected call changed during inspection")
                return None
            if selected_before.get("sourceContentVersion") is None:
                reject("anchor", "source content version unavailable")
                return None
            if selected_before.get("targetContentVersionAfter") is None:
                reject("anchor", "target content version unavailable")
                return None
            if selected_before.get("canvasId") != trace_id:
                reject("anchor", "selected canvas identity mismatch")
                return None
            snapshot_fields = ("snapshotId", "fullSourceSnapshotId", "targetSnapshotId")
            if any(selected_before.get(field) is None for field in snapshot_fields):
                reject("anchor", "immutable snapshot reference unavailable")
                return None
            if (
                isinstance(before, dict)
                and isinstance(after, dict)
                and (
                    before.get("traceId") != after.get("traceId")
                    or before.get("geometryToken") != after.get("geometryToken")
                    or before.get("geometryVersion") != after.get("geometryVersion")
                    or before.get("geometryHistoryIncomplete")
                    or after.get("geometryHistoryIncomplete")
                    or before.get("selected") != after.get("selected")
                )
            ):
                changed_fields = [
                    field
                    for field in (
                        "traceId",
                        "geometryToken",
                        "geometryVersion",
                        "geometryHistoryIncomplete",
                        "selected",
                    )
                    if before.get(field) != after.get(field)
                ]
                before_selected = before.get("selected")
                after_selected = after.get("selected")
                selected_fields = (
                    "canvasId",
                    "operationIndex",
                    "sourceId",
                    "sourceCanvasId",
                    "snapshotId",
                    "fullSourceSnapshotId",
                    "targetSnapshotId",
                    "sourceContentVersion",
                    "targetContentVersionAfter",
                )
                before_selected_summary = (
                    {
                        field: before_selected.get(field)
                        for field in selected_fields
                        if field in before_selected
                    }
                    if isinstance(before_selected, dict)
                    else None
                )
                after_selected_summary = (
                    {
                        field: after_selected.get(field)
                        for field in selected_fields
                        if field in after_selected
                    }
                    if isinstance(after_selected, dict)
                    else None
                )
                reject(
                    "anchor",
                    "trace or geometry anchor changed",
                    changed_fields=changed_fields,
                    history_incomplete_before=before.get("geometryHistoryIncomplete"),
                    history_incomplete_after=after.get("geometryHistoryIncomplete"),
                    trace_id_before=before.get("traceId"),
                    trace_id_after=after.get("traceId"),
                    geometry_token_before=before.get("geometryToken"),
                    geometry_token_after=after.get("geometryToken"),
                    geometry_version_before=before.get("geometryVersion"),
                    geometry_version_after=after.get("geometryVersion"),
                    selected_before=before_selected_summary,
                    selected_after=after_selected_summary,
                    initial_anchor=anchor_summary(initial_anchor),
                    anchor_before=anchor_summary(before),
                    anchor_after=anchor_summary(after),
                )
                return None
            if not isinstance(decoded, dict):
                reject("hash", "native crop hash unavailable")
                return None
            if (
                initial_anchor.get("geometryToken") is None
                or initial_anchor.get("geometryVersion") is None
                or after.get("geometryToken") is None
                or after.get("geometryVersion") is None
            ):
                reject("anchor", "geometry token unavailable")
                return None
            self._terminal_reinspection_raw_success_anchor = dict(initial_anchor)
            return {
                "traceId": trace_id,
                "operationIndex": operation_index,
                "sourceId": selected_call.get("sourceId"),
                "sourceCanvasId": selected_call.get("sourceCanvasId"),
                "sourceConstructor": (selected_call.get("source") or {}).get("constructor"),
                "sourceDimensions": [round(source_width), round(source_height)],
                "sourceContentVersion": selected_call.get("sourceContentVersion"),
                "targetContentVersionAfter": selected_call.get(
                    "targetContentVersionAfter"
                ),
                "sourceRect": self._safe_diagnostic_value(selected_call.get("sourceRect")),
                "cropVariant": crop_variant,
                "destination": self._safe_diagnostic_value(selected_call.get("destination")),
                "targetDimensions": [width, height],
                "width": decoded.get("width"),
                "height": decoded.get("height"),
                "rgbaSha256": decoded.get("rgbaSha256"),
                "cropSignature": {
                    "sourceDimensions": [round(source_width), round(source_height)],
                    "sourceRect": [source_x, source_y, source_rect_width, source_rect_height],
                    "outputDimensions": [decoded.get("width"), decoded.get("height")],
                },
                "anchorBefore": self._safe_diagnostic_value(before),
                "anchorAfter": self._safe_diagnostic_value(after),
                "initialAnchor": self._safe_diagnostic_value(initial_anchor),
            }
        except (
            BinasciiError,
            KeyError,
            LookupError,
            PlaywrightError,
            PlaywrightTimeoutError,
            TimeoutError,
            TypeError,
            ValueError,
        ) as exc:
            reject("exception", "native artifact inspection raised a bounded exception", exception_type=type(exc).__name__)
            return None

    async def _approx_terminal_canvas(
        self,
        canvas: Locator,
        role: str,
        *,
        expected_content_id: str,
        expected_counter: str,
    ) -> dict[str, Any] | None:
        """Match a complete, stable rendered terminal canvas by image descriptor.

        This is intentionally independent of native source identity and JPEG
        candidates.  The canvas is read as one complete image before any
        geometry splitting, and both reads must describe the same actual DOM
        canvas.  A non-white canvas or any unstable
        read fails closed.
        """

        try:
            if not expected_content_id.strip() or not expected_counter.strip():
                return None
            # Pin the resolved DOM element.  Re-evaluating the Locator could
            # otherwise retarget a replacement renderer canvas between reads.
            element = await canvas.element_handle()
            if element is None:
                return None
            before_raw = await element.evaluate(TERMINAL_DESCRIPTOR_SCRIPT)
            if not isinstance(before_raw, dict):
                return None
            before_png = decode_terminal_data_url(before_raw.get("dataUrl"))
            before = describe_terminal_png(before_png) if before_png else None
            if before is None:
                return None
            if (
                before_raw.get("contentId") != expected_content_id
                or before_raw.get("counter") != expected_counter
            ):
                return None
            trace_id = before_raw.get("traceId")
            matched, details = match_terminal_descriptor(before, role)
            if not matched:
                return None
            after_raw = await element.evaluate(TERMINAL_DESCRIPTOR_SCRIPT)
            if not isinstance(after_raw, dict):
                return None
            after_png = decode_terminal_data_url(after_raw.get("dataUrl"))
            after = describe_terminal_png(after_png) if after_png else None
            if after is None:
                return None
            if any(before_raw.get(field) != after_raw.get(field) for field in (
                "contentId", "counter", "width", "height"
            )):
                return None
            if (
                after_raw.get("contentId") != expected_content_id
                or after_raw.get("counter") != expected_counter
            ):
                return None
            before_trace = before_raw.get("traceId")
            after_trace = after_raw.get("traceId")
            if before_trace and after_trace and before_trace != after_trace:
                return None
            if before.get("frameSha256") != after.get("frameSha256"):
                return None
            matched_after, after_details = match_terminal_descriptor(after, role)
            if not matched_after or after_details.get("role") != role:
                return None
            return {
                "kind": "approximate_complete_canvas",
                "role": role,
                "traceId": trace_id,
                "contentId": before_raw.get("contentId"),
                "counter": before_raw.get("counter"),
                "width": before.get("width"),
                "height": before.get("height"),
                "frameSha256": before.get("frameSha256"),
                "descriptor": details,
            }
        except (
            AttributeError,
            PlaywrightError,
            PlaywrightTimeoutError,
            TimeoutError,
            TypeError,
            ValueError,
        ):
            return None

    async def _terminal_ad_state(self, page: Page) -> tuple[bool, dict[str, Any]]:
        current, total, counter_text = await self._read_page_counter_pair(page)
        result: dict[str, Any] = {
            "counter": counter_text,
            "current": current,
            "total": total,
            "role": None,
            "matched": False,
            "reason": "counter unavailable",
        }
        if current is None or total is None or total <= 1:
            return False, result
        if current == total - 1:
            role = "notice"
        elif current == total:
            role = "logo"
        else:
            result["reason"] = "not terminal role position"
            return False, result
        result["role"] = role
        if not isinstance(self._initial_content_id, str) or not self._initial_content_id.strip():
            result["reason"] = "authorized content identity unavailable"
            return False, result
        try:
            canvas = await self.get_capture_target(page)
        except (
            LookupError,
            PlaywrightError,
            PlaywrightTimeoutError,
            TimeoutError,
        ):
            result["reason"] = "capture target unavailable"
            return False, result
        approximate = await self._approx_terminal_canvas(
            canvas,
            role,
            expected_content_id=self._initial_content_id,
            expected_counter=counter_text,
        )
        if approximate is not None:
            after_current, after_total, after_counter = await self._read_page_counter_pair(page)
            approximate_cid = approximate.get("contentId")
            cid_stable = (
                isinstance(approximate_cid, str)
                and approximate_cid.casefold() == self._initial_content_id.casefold()
            )
            if (
                (after_current, after_total) == (current, total)
                and after_counter == counter_text
                and cid_stable
            ):
                result["artifact"] = approximate
                result["matched"] = True
                result["reason"] = "stable complete-canvas terminal image"
                key = (role, current, total, "approx", approximate["frameSha256"])
                if self._last_terminal_diagnostic_key != key:
                    self._append_diagnostic({"kind": "terminal_artifact", **result})
                    self._last_terminal_diagnostic_key = key
                return True, result
        try:
            artifact = await self._native_terminal_artifact(page, canvas)
        except (
            LookupError,
            PlaywrightError,
            PlaywrightTimeoutError,
            TimeoutError,
        ):
            artifact = None
        if artifact is None:
            result["reason"] = "native artifact unavailable or terminal layout unmatched"
            key = (role, current, total, "unavailable")
            if self._last_terminal_diagnostic_key != key:
                self._append_diagnostic({"kind": "terminal_artifact", **result})
                self._last_terminal_diagnostic_key = key
            return False, result
        result["artifact"] = artifact
        after_current, after_total, after_counter = await self._read_page_counter_pair(page)
        if (
            (after_current, after_total) != (current, total)
            or after_counter != counter_text
        ):
            result["reason"] = "counter changed during native artifact inspection"
            artifact["counterStable"] = False
        else:
            artifact["counterStable"] = True
        key = (
            role,
            current,
            total,
            artifact.get("width"),
            artifact.get("height"),
            artifact.get("rgbaSha256"),
        )
        expected_role = self._known_terminal_native_artifacts.get(
            (
                artifact.get("width"),
                artifact.get("height"),
                artifact.get("rgbaSha256"),
            )
        )
        if expected_role != role:
            result["reason"] = "unknown native artifact or role mismatch"
        elif artifact.get("counterStable") is not True:
            result["reason"] = "counter changed during native artifact inspection"
        else:
            result["matched"] = True
            result["reason"] = "known native terminal artifact"
        if self._last_terminal_diagnostic_key != key:
            self._append_diagnostic({"kind": "terminal_artifact", **result})
            self._last_terminal_diagnostic_key = key
        return result["matched"] is True, result

    async def _persist_capture_diagnostic(self, page: Page) -> None:
        if self._diagnostics_path is None:
            return
        capture = self._capture_debug.get("bookwalker_capture", {})
        current, total, counter = await self._read_page_counter_pair(page)
        if (
            capture.get("returned_path") in {
                "original_jpeg",
                "direct_original_jpeg",
                "reconstructed_jpeg",
            }
            and current not in {1, total}
            and capture.get("failure_reason") is None
        ):
            self._diagnostics_omitted_successes += 1
            return
        selected = capture.get("selected_draw", [])
        self._append_diagnostic(
            {
                "kind": "capture",
                "omitted_successful_captures_before": self._diagnostics_omitted_successes,
                "counter": counter,
                "current": current,
                "total": total,
                "returned_path": capture.get("returned_path"),
                "failure_reason": capture.get("failure_reason"),
                "candidate_count": len(self._original_candidates),
                "matcher_attempted": bool(
                    (capture.get("original_match") or {}).get(
                        "original_attempt_count"
                    )
                ),
                "native_selection": self._safe_diagnostic_value(
                    capture.get("native_selection")
                ),
                "original_match": self._safe_diagnostic_value(
                    capture.get("original_match")
                ),
                "selected_draw": self._safe_diagnostic_value(selected),
                "direct_original_jpeg": self._safe_diagnostic_value(
                    capture.get("direct_original_jpeg")
                ),
                "lossless_shadow": self._safe_diagnostic_value(
                    capture.get("lossless_shadow")
                ),
            }
        )

    def get_initialize_timeout_ms(self, default_ms: int) -> int:
        """Allow the bounded BookWalker login navigation budget to complete."""

        return max(default_ms, self.initialize_timeout_ms)

    async def login(
        self,
        page: Page,
        *,
        email: str,
        password: str,
        home_url: str = "https://bookwalker.jp/",
    ) -> None:
        """Run the site-specific login flow on an existing browser page."""

        await login_bookwalker(page, email=email, password=password, home_url=home_url)

    @staticmethod
    def content_id_from_url(url: str) -> str | None:
        parsed = urlparse(url)
        values = parse_qs(parsed.query).get("cid", [])
        if values:
            return values[0]

        # Product pages use /de<content-id>/ while the viewer uses ?cid=.
        match = re.search(
            r"/de([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})(?:/|$)",
            parsed.path,
            re.IGNORECASE,
        )
        return match.group(1) if match else None

    @staticmethod
    def parse_page_counter(text: str) -> tuple[int | None, str | None]:
        normalized = " ".join(text.split())
        if not normalized:
            return None, None
        match = re.search(r"\d+", normalized)
        return (int(match.group(0)), normalized) if match else (None, normalized)

    @staticmethod
    def score_read_link(candidate: dict[str, str | None], content_id: str | None) -> int:
        """Rank product-page links that can enter a reader.

        BookWalker changes the action label depending on ownership and
        subscription status. The product content ID and reader URL are
        stronger signals than DOM order, which may put the trial link first.
        """

        text = (candidate.get("text") or "").strip()
        action = (candidate.get("action") or "").strip().lower()
        href = (candidate.get("href") or "").lower()
        uuid = candidate.get("uuid")
        score = 0

        if content_id and uuid == content_id:
            score += 100
        if "viewer" in href:
            score += 100
        if action and action != "trial_reading" and any(
            token in action for token in ("read", "reading", "subscription")
        ):
            score += 80
        if "10\u5206" in text or "\u307e\u308b\u8aad\u307f" in text:
            score += 80
        elif "\u8aad\u3080" in text or "\u8aad\u307f" in text:
            score += 50
        if "10分" in text or "まる読み" in text:
            score += 80
        elif "読む" in text or "読み" in text:
            score += 50
        if action == "trial_reading":
            score += 10
        if "sample=1" in href:
            score += 5
        if action == "more_read":
            score -= 100
        return score

    @staticmethod
    def is_read_link_candidate(candidate: dict[str, str | None]) -> bool:
        """Return whether a product-page anchor can enter a reader."""
        return is_reader_control_candidate(candidate)

    async def _visible(self, locator: Locator) -> bool:
        try:
            return await asyncio.wait_for(locator.is_visible(timeout=500), timeout=1)
        except PlaywrightTimeoutError:
            return False
        except TimeoutError:
            return False

    async def _renderer_ready(self, page: Page) -> bool:
        return await self._visible_canvas(page) is not None

    async def _visible_canvas(self, page: Page) -> Locator | None:
        renderer = page.locator("#renderer")
        if not await self._visible(renderer):
            return None

        current = page.locator("#renderer .currentScreen canvas:not(.dummy)")
        candidates = current if await current.count() else page.locator(
            "#renderer canvas:not(.dummy)"
        )
        for index in range(await candidates.count()):
            canvas = candidates.nth(index)
            try:
                box = await asyncio.wait_for(canvas.bounding_box(), timeout=1)
                size = await asyncio.wait_for(
                    canvas.evaluate("element => ({width: element.width, height: element.height})"),
                    timeout=1,
                )
            except (PlaywrightTimeoutError, TimeoutError):
                continue
            if (
                await self._visible(canvas)
                and box
                and box["width"] > 0
                and box["height"] > 0
                and size["width"] > 0
                and size["height"] > 0
            ):
                return canvas
        return None

    async def _canvas_signature(self, page: Page) -> tuple[int, int] | None:
        canvas = await self._visible_canvas(page)
        if canvas is None:
            return None
        try:
            return await asyncio.wait_for(
                canvas.evaluate(
                    """
                    element => {
                      const probe = document.createElement('canvas');
                      window.__bookwalkerMarkInternalCanvas?.(probe);
                      probe.width = 64;
                      probe.height = 64;
                      const probeContext = probe.getContext('2d');
                      if (!probeContext) return [0, 0];
                      probeContext.drawImage(element, 0, 0, 64, 64);
                      const sample = probeContext.getImageData(0, 0, 64, 64).data;
                      let nonWhite = 0;
                      let checksum = 0;
                      for (let offset = 0; offset < sample.length; offset += 4) {
                        checksum = (checksum * 31 + sample[offset]) >>> 0;
                        checksum = (checksum * 31 + sample[offset + 1]) >>> 0;
                        checksum = (checksum * 31 + sample[offset + 2]) >>> 0;
                        checksum = (checksum * 31 + sample[offset + 3]) >>> 0;
                        if (
                          sample[offset] < 245 ||
                          sample[offset + 1] < 245 ||
                          sample[offset + 2] < 245 ||
                          sample[offset + 3] < 245
                        ) {
                          nonWhite += 1;
                        }
                      }
                      return [checksum, nonWhite];
                    }
                    """
                ),
                timeout=2,
            )
        except (PlaywrightTimeoutError, TimeoutError):
            return None

    async def _has_viewer_shell(self, page: Page) -> bool:
        for selector in ("#viewer", "#renderer"):
            try:
                if await asyncio.wait_for(page.locator(selector).count(), timeout=1):
                    return True
            except TimeoutError:
                continue
        return False

    async def _wait_for_render_ready(self, page: Page) -> None:
        """Wait for the gray loading overlay to disappear and stay gone."""

        elapsed_ms = 0
        stable_checks = 0
        previous_signature: tuple[int, int] | None = None
        while elapsed_ms < self.page_change_timeout_ms:
            loading = await self._visible(page.locator("#loaderStatusDialog"))
            ready = await self._renderer_ready(page)
            if not loading and ready:
                signature = await self._canvas_signature(page)
                if (
                    signature is not None
                    and signature[1] > 0
                    and signature == previous_signature
                ):
                    stable_checks += 1
                else:
                    stable_checks = 0
                previous_signature = signature
                if stable_checks >= self.render_stable_checks:
                    return
            else:
                stable_checks = 0
                previous_signature = None
            await page.wait_for_timeout(100)
            elapsed_ms += 100
        raise PageChangeTimeoutError(
            "BookWalker viewer did not finish loading within the timeout"
        )

    async def _last_page_end_marker_visible(self, page: Page) -> bool:
        """Give the viewer time to expose END after rendering its logo screen."""

        counter = page.locator("#pageSliderCounter")
        if not await counter.count():
            return False
        try:
            raw_counter = await asyncio.wait_for(counter.inner_text(timeout=1000), timeout=1)
        except (PlaywrightTimeoutError, TimeoutError):
            return False
        if not is_last_page_counter(raw_counter):
            return False

        elapsed_ms = 0
        while elapsed_ms < self.end_marker_grace_ms:
            if await self._visible(page.locator("#endOfBook")):
                return True
            await page.wait_for_timeout(100)
            elapsed_ms += 100
        return await self._visible(page.locator("#endOfBook"))

    async def _is_last_page_counter(self, page: Page) -> bool:
        counter = page.locator("#pageSliderCounter")
        if not await counter.count():
            return False
        try:
            raw_counter = await asyncio.wait_for(counter.inner_text(timeout=1000), timeout=1)
        except (PlaywrightTimeoutError, TimeoutError):
            return False
        return is_last_page_counter(raw_counter)

    async def _find_read_link(self, page: Page) -> Locator | None:
        elapsed_ms = 0
        deferred_trial: Locator | None = None
        while elapsed_ms < self.read_link_wait_timeout_ms:
            best_link: Locator | None = None
            best_score = -1
            # These containers identify the product's own reading controls.
            # Some product variants render the control as a button, or attach
            # its destination through JavaScript instead of an href.
            for selector in (
                (
                    '#js-read-check a, #js-read-check button, '
                    '#js-read-check [role="button"], #js-read-check [data-action-label]'
                ),
                (
                    '#js-subscription-check a, #js-subscription-check button, '
                    '#js-subscription-check [role="button"], '
                    '#js-subscription-check [data-action-label]'
                ),
            ):
                locator = page.locator(selector)
                try:
                    count = await asyncio.wait_for(locator.count(), timeout=1)
                except TimeoutError:
                    continue
                for index in range(count):
                    candidate = locator.nth(index)
                    if not await self._visible(candidate):
                        continue
                    try:
                        metadata = await asyncio.wait_for(
                            candidate.evaluate(
                                """
                                element => ({
                                  text: element.innerText ||
                                    element.getAttribute('aria-label') ||
                                    element.getAttribute('title') || '',
                                  action: element.getAttribute('data-action-label'),
                                  href: element.href ||
                                    element.getAttribute('data-href') ||
                                    element.getAttribute('data-url') || '',
                                  uuid: element.getAttribute('data-uuid')
                                })
                                """
                            ),
                            timeout=1,
                        )
                    except (PlaywrightTimeoutError, TimeoutError):
                        continue
                    if not self.is_read_link_candidate(metadata):
                        continue
                    score = self.score_read_link(metadata, self._initial_content_id)
                    if score > best_score:
                        best_link = candidate
                        best_score = score
            if best_link is not None:
                # Give stronger owned/subscription links a short opportunity
                # to appear after the initial product-page DOM is rendered.
                # Trial is a safe fallback, but must not win merely by arriving
                # earlier than the real reading control.
                if best_score >= 180:
                    return best_link
                deferred_trial = best_link

            # Fallbacks cover product-page variants that omit the standard
            # containers or use a direct viewer URL.
            selectors = (
                'a[href*="viewer.bookwalker.jp"]',
                'a[data-action-label="reading"]',
                'a[data-action-label="read"]',
                'a[data-action-label="trial_reading"]',
                'a[data-action-label="read_maruyomi"]',
                'button[data-action-label="reading"]',
                'button[data-action-label="read"]',
                'button[data-action-label="trial_reading"]',
                'button[data-action-label="read_maruyomi"]',
            )
            for selector in selectors:
                locator = page.locator(selector)
                try:
                    count = await asyncio.wait_for(locator.count(), timeout=1)
                except TimeoutError:
                    continue
                for index in range(count):
                    candidate = locator.nth(index)
                    if await self._visible(candidate):
                        if selector.endswith('"trial_reading"]') and elapsed_ms < 800:
                            continue
                        return candidate
            await page.wait_for_timeout(100)
            elapsed_ms += 100
        return deferred_trial

    async def _reader_control_metadata(
        self, candidate: Locator
    ) -> dict[str, str | None]:
        return await asyncio.wait_for(
            candidate.evaluate(
                """
                element => ({
                  text: element.innerText ||
                    element.getAttribute('aria-label') ||
                    element.getAttribute('title') || '',
                  action: element.getAttribute('data-action-label'),
                  href: element.href ||
                    element.getAttribute('data-href') ||
                    element.getAttribute('data-url') || '',
                  uuid: element.getAttribute('data-uuid')
                })
                """
            ),
            timeout=1,
        )

    async def _dom_identity(self, candidate: Locator) -> str:
        """Return a non-mutating identity for one DOM element."""

        return await asyncio.wait_for(
            candidate.evaluate(
                """
                element => {
                  const parts = [];
                  let current = element;
                  while (current && current.nodeType === Node.ELEMENT_NODE) {
                    let index = 0;
                    for (let sibling = current; sibling; sibling = sibling.previousElementSibling) {
                      index += 1;
                    }
                    parts.unshift(`${current.tagName}:${index}`);
                    current = current.parentElement;
                  }
                  return parts.join('/');
                }
                """
            ),
            timeout=1,
        )

    async def _is_control_element(self, candidate: Locator) -> bool:
        return await asyncio.wait_for(
            candidate.evaluate(
                """
                element => element.matches(
                  'a, button, [role="button"], [data-action-label]'
                )
                """
            ),
            timeout=1,
        )

    async def _strict_control_candidates(
        self, page: Page, expected_kind: ReaderControlKind
    ) -> tuple[
        list[tuple[Locator, dict[str, str | None], str]],
        list[ReaderControlKind],
    ]:
        """Collect exact-kind controls from the product's own action scopes."""

        matches: list[tuple[Locator, dict[str, str | None], str]] = []
        observed: list[ReaderControlKind] = []
        seen_elements: set[str] = set()
        for scope_selector in self._strict_scope_selectors:
            scope = page.locator(scope_selector)
            try:
                scope_count = await asyncio.wait_for(scope.count(), timeout=1)
            except (PlaywrightTimeoutError, TimeoutError):
                continue
            for scope_index in range(scope_count):
                scope_element = scope.nth(scope_index)
                controls = scope_element.locator(self._strict_control_selector)
                candidates: list[Locator] = []
                try:
                    if await self._is_control_element(scope_element):
                        candidates.append(scope_element)
                except (PlaywrightTimeoutError, TimeoutError):
                    pass
                try:
                    control_count = await asyncio.wait_for(controls.count(), timeout=1)
                except (PlaywrightTimeoutError, TimeoutError):
                    control_count = 0
                candidates.extend(controls.nth(index) for index in range(control_count))
                for candidate in candidates:
                    try:
                        if not await self._visible(candidate):
                            continue
                        identity = await self._dom_identity(candidate)
                        if identity in seen_elements:
                            continue
                        seen_elements.add(identity)
                        metadata = await self._reader_control_metadata(candidate)
                    except (PlaywrightTimeoutError, TimeoutError):
                        continue

                    kind = classify_reader_control(metadata)
                    observed.append(kind)
                    uuid = (metadata.get("uuid") or "").strip()
                    if (
                        uuid
                        and (
                            self._initial_content_id is None
                            or uuid.casefold() != self._initial_content_id.casefold()
                        )
                    ):
                        continue
                    if kind is expected_kind:
                        matches.append((candidate, metadata, identity))
        return matches, observed

    @staticmethod
    def _strict_candidate_signature(
        metadata: dict[str, str | None], identity: str
    ) -> tuple[str, ...]:
        """Return the stable, in-browser identity used for strict entry."""

        return (
            identity,
            metadata.get("action") or "",
            metadata.get("text") or "",
            metadata.get("href") or "",
            metadata.get("uuid") or "",
        )

    def _strict_entry_error(
        self,
        *,
        expected_kind: ReaderControlKind,
        observed: list[ReaderControlKind],
        reason: str,
    ) -> BookWalkerStrictEntryError:
        return BookWalkerStrictEntryError(
            strategy=self._access_strategy,
            expected_kind=expected_kind,
            observed_kinds=observed,
            reason=reason,
        )

    def _strict_expected_kind(self) -> ReaderControlKind:
        return (
            ReaderControlKind.OWNED
            if self._access_strategy == "direct"
            else ReaderControlKind.MARUYOMI
        )

    async def _find_strict_read_link(
        self, page: Page, expected_kind: ReaderControlKind
    ) -> Locator:
        elapsed_ms = 0
        observed: list[ReaderControlKind] = []
        stable_signature: tuple[str, ...] | None = None
        stable_samples = 0
        last_matches: list[tuple[Locator, dict[str, str | None], str]] = []

        # The product page can briefly contain both the old and new control
        # while its access action scope is being replaced.  Keep this settle
        # bounded by the existing timeout and leave enough time for at least
        # one candidate observation in short unit-test timeouts.
        initial_settle_ms = min(
            self.strict_entry_initial_settle_ms,
            max(0, self.read_link_wait_timeout_ms - self.strict_candidate_poll_interval_ms),
        )
        if initial_settle_ms:
            await page.wait_for_timeout(initial_settle_ms)
            elapsed_ms += initial_settle_ms

        while elapsed_ms < self.read_link_wait_timeout_ms:
            matches, observed = await self._strict_control_candidates(page, expected_kind)
            if len(matches) == 1:
                candidate, metadata, identity = matches[0]
                signature = self._strict_candidate_signature(metadata, identity)
                if signature == stable_signature:
                    stable_samples += 1
                else:
                    stable_signature = signature
                    stable_samples = 1
                last_matches = matches
                if stable_samples >= self.strict_candidate_stability_samples:
                    return candidate
            else:
                # Zero candidates and transient ambiguity both invalidate the
                # previous sample.  A persistent ambiguity therefore remains
                # fail-safe, but no longer fails on the first DOM snapshot.
                stable_signature = None
                stable_samples = 0
                last_matches = matches

            remaining_ms = self.read_link_wait_timeout_ms - elapsed_ms
            if remaining_ms <= 0:
                break
            wait_ms = min(self.strict_candidate_poll_interval_ms, remaining_ms)
            await page.wait_for_timeout(wait_ms)
            elapsed_ms += wait_ms

        reason = "no matching control was observed before timeout"
        if len(last_matches) > 1 or any(
            kind is expected_kind for kind in observed
        ):
            reason = "matching control was not stably unique before timeout"
        elif observed and all(kind is ReaderControlKind.UNKNOWN for kind in observed):
            reason = "visible controls are unsupported or unknown"
        raise self._strict_entry_error(
            expected_kind=expected_kind,
            observed=observed,
            reason=reason,
        )

    async def _wait_for_url_change(self, page: Page, previous_url: str) -> None:
        elapsed_ms = 0
        while elapsed_ms < self.navigation_wait_timeout_ms:
            if page.url != previous_url:
                return
            await page.wait_for_timeout(100)
            elapsed_ms += 100
        raise PageChangeTimeoutError(
            "BookWalker read button did not navigate to a viewer"
        )

    async def _open_reader_from_product(self, page: Page) -> None:
        link = await self._find_read_link(page)
        if link is None:
            raise LookupError(
                "BookWalker read button was not found on the product page"
            )

        await self._activate_reader_control(page, link)

    async def _activate_reader_control(self, page: Page, link: Locator) -> None:
        previous_url = page.url
        # Product pages may mark the read link target=_blank. Remove only that
        # presentation detail so the existing Runner Page follows the click.
        # The click itself remains a normal user-facing link activation.
        try:
            await asyncio.wait_for(
                link.evaluate("element => element.removeAttribute('target')"),
                timeout=1,
            )
            # Some BookWalker links schedule navigation in a script and keep
            # the click promise pending while the new document is loading.
            # The adapter has its own bounded URL-change wait below, so do not
            # make Playwright wait for scheduled navigations here.
            await link.click(force=True, timeout=3_000, no_wait_after=True)
        except (PlaywrightTimeoutError, TimeoutError) as exc:
            raise PageChangeTimeoutError(
                "BookWalker read button could not be activated"
            ) from exc
        await self._wait_for_url_change(page, previous_url)

    async def _is_viewer_destination(self, page: Page) -> bool:
        parsed = urlparse(page.url)
        return parsed.netloc.lower() == "viewer.bookwalker.jp" or await self._has_viewer_shell(
            page
        )

    async def _wait_for_strict_entry_destination(self, page: Page) -> str | None:
        """Wait until strict entry resolves to viewer or a login form."""

        elapsed_ms = 0
        while True:
            if await self._is_viewer_destination(page):
                return "viewer"
            if await is_bookwalker_login_page(page):
                return "login"

            remaining_ms = self.navigation_wait_timeout_ms - elapsed_ms
            if remaining_ms <= 0:
                return None
            poll_interval_ms = max(1, self.strict_entry_destination_poll_interval_ms)
            wait_ms = min(poll_interval_ms, remaining_ms)
            await page.wait_for_timeout(wait_ms)
            elapsed_ms += wait_ms

    async def _open_strict_reader_from_product(self, page: Page) -> None:
        expected_kind = self._strict_expected_kind()
        link = await self._find_strict_read_link(page, expected_kind)
        await self._activate_reader_control(page, link)

        destination = await self._wait_for_strict_entry_destination(page)
        if destination is None:
            raise self._strict_entry_error(
                expected_kind=expected_kind,
                observed=[expected_kind],
                reason="strict entry destination did not resolve to viewer or login form",
            )

        if destination == "login":
            if self._access_strategy != "quota":
                raise self._strict_entry_error(
                    expected_kind=expected_kind,
                    observed=[expected_kind],
                    reason="strict entry reached a BookWalker login form",
                )
            if self._auto_login_attempted:
                raise self._strict_entry_error(
                    expected_kind=expected_kind,
                    observed=[expected_kind],
                    reason="BookWalker auto-login was already attempted in this run",
                )
            self._auto_login_attempted = True
            if not self._auto_login_email or not self._auto_login_password:
                raise BookWalkerLoginError(
                    "BookWalker auto-login is required but "
                    "BOOKWALKER_EMAIL / BOOKWALKER_PASSWORD are not configured"
                )
            await submit_bookwalker_login_form(
                page,
                email=self._auto_login_email,
                password=self._auto_login_password,
            )
            if not await self._is_viewer_destination(page):
                raise self._strict_entry_error(
                    expected_kind=expected_kind,
                    observed=[expected_kind],
                    reason="BookWalker auto-login did not reach the target viewer",
                )
        viewer_content_id = self.content_id_from_url(page.url)
        if (
            self._initial_content_id is not None
            and viewer_content_id is not None
            and viewer_content_id.casefold() != self._initial_content_id.casefold()
        ):
            raise self._strict_entry_error(
                expected_kind=expected_kind,
                observed=[expected_kind],
                reason=(
                    "viewer content id does not match product content id "
                    f"({viewer_content_id!r})"
                ),
            )

    async def _collect_product_metadata(self, page: Page) -> None:
        """Read title/author/volume before the product page becomes the viewer."""

        current_id = self._initial_content_id
        data = await page.evaluate(
            r"""
            currentId => {
              const mainTitle = document.querySelector(
                'h1.t-c-product-main-data__title'
              );
              const authorBlock = document.querySelector(
                '.t-c-product-main-data__authors'
              );
              const authorLinks = authorBlock
                ? [...authorBlock.querySelectorAll('a')].map(a => (a.innerText || '').trim())
                : [];
              const category = [...document.querySelectorAll('dt')].find(dt =>
                (dt.innerText || '').trim() === 'カテゴリ'
              )?.nextElementSibling?.innerText || '';
              const seriesHeading = [...document.querySelectorAll('#js-scroll-series h2')]
                .map(element => element.innerText || '')
                .find(text => text.includes('シリーズ一覧')) || '';
              const seriesCountMatch = seriesHeading.match(/[（(]\s*(\d+)\s*冊[）)]/);
              let seriesTitle = '';
              for (const card of document.querySelectorAll('#js-series-list article')) {
                const hrefs = [...card.querySelectorAll('a[href]')].map(a => a.href);
                const productPath = currentId ? `/de${currentId}/` : '';
                if (productPath && hrefs.some(href => {
                  try {
                    const url = new URL(href);
                    return url.hostname === 'bookwalker.jp' &&
                      url.pathname.toLowerCase() === productPath.toLowerCase();
                  } catch (error) {
                    return false;
                  }
                })) {
                  seriesTitle = card.querySelector('h3')?.innerText || '';
                  break;
                }
              }
              return {
                main_title: mainTitle?.innerText || '',
                author_text: authorBlock?.innerText || '',
                author_links: authorLinks,
                category,
                series_title: seriesTitle,
                series_count: seriesCountMatch ? Number(seriesCountMatch[1]) : null,
              };
            }
            """,
            current_id,
        )
        raw_title = data.get("series_title") or data.get("main_title") or ""
        series_count = data.get("series_count")
        self._series_count = int(series_count) if series_count is not None else None
        self._output_title, self._output_volume = split_bookwalker_title(
            raw_title,
            series_count=self._series_count,
        )

        author_text = " ".join(str(data.get("author_text") or "").split())
        role_boundary = re.search(r"\s+(?:イラスト|原作|作画|漫画|訳|監修)", author_text)
        author_part = author_text[: role_boundary.start()] if role_boundary else author_text
        author_part = re.sub(r"^著\s*", "", author_part).strip()
        link_names = [
            "".join(str(name).split())
            for name in data.get("author_links", [])
            if str(name).strip() and str(name).replace(" ", "") in author_part.replace(" ", "")
        ]
        if link_names:
            self._output_author = "・".join(dict.fromkeys(link_names))
        else:
            self._output_author = author_part.replace(" ", "") or None

        category = str(data.get("category") or "")
        if "マンガ" in category:
            self._output_genre = "漫画"
        elif "技術" in category:
            self._output_genre = "技術書"
        elif "雑誌" in category:
            self._output_genre = "雑誌"
        else:
            self._output_genre = "小説"

    async def _remember_viewer_title(self, page: Page) -> None:
        if self._output_title:
            return
        title_locator = page.locator("#pagetitle")
        if await title_locator.count():
            try:
                raw_title = (
                    await asyncio.wait_for(title_locator.inner_text(timeout=1000), timeout=1)
                ).strip()
            except (PlaywrightTimeoutError, TimeoutError):
                raw_title = ""
            self._output_title, self._output_volume = split_bookwalker_title(
                raw_title,
                series_count=self._series_count,
            )

    async def initialize(self, page: Page) -> None:
        self._initial_content_id = self.content_id_from_url(page.url)
        has_viewer_shell = await self._has_viewer_shell(page)
        parsed = urlparse(page.url)
        is_product_page = parsed.netloc.lower() in {
            "bookwalker.jp",
            "www.bookwalker.jp",
        } and bool(re.match(r"^/de[0-9a-f-]+/?$", parsed.path, re.IGNORECASE))
        is_viewer_url = parsed.netloc.lower() == "viewer.bookwalker.jp"

        if self._access_strategy != "auto" and (has_viewer_shell or is_viewer_url):
            raise self._strict_entry_error(
                expected_kind=self._strict_expected_kind(),
                observed=[],
                reason="strict entry requires a product page, but the run is already in a viewer",
            )

        if (
            self._access_strategy != "auto"
            and is_product_page
            and self._initial_content_id is None
        ):
            raise self._strict_entry_error(
                expected_kind=self._strict_expected_kind(),
                observed=[],
                reason=(
                    "product identity/content UUID could not be determined "
                    "from the product URL"
                ),
            )

        if not has_viewer_shell and is_product_page:
            await self._collect_product_metadata(page)
            if self._access_strategy == "auto":
                await self._open_reader_from_product(page)
            else:
                await self._open_strict_reader_from_product(page)
            self._initial_content_id = self.content_id_from_url(page.url)
        elif self._access_strategy != "auto":
            raise self._strict_entry_error(
                expected_kind=self._strict_expected_kind(),
                observed=[],
                reason="strict entry requires a BookWalker product page",
            )

        await self._wait_for_render_ready(page)
        await self._remember_viewer_title(page)

    def get_output_metadata(self) -> dict[str, str | None]:
        return {
            "title": self._output_title,
            "author": self._output_author,
            "volume": self._output_volume,
            "genre": self._output_genre,
        }

    async def prepare_page(self, page: Page) -> None:
        native_mode_script = (
            "window.__bookwalkerCaptureMode = "
            f"{self.capture_mode!r};"
            "window.__bookwalkerDirectOriginalEnabled = "
            f"{str(self.capture_mode == 'native' and self.enable_original_jpeg_capture).lower()};"
        )
        await page.add_init_script(native_mode_script + "\n" + _DRAW_TRACE_SCRIPT)
        if self.capture_mode != "native" or not self.enable_original_jpeg_capture:
            return
        for task in tuple(self._original_response_tasks):
            task.cancel()
        if self._original_response_tasks:
            await asyncio.gather(
                *self._original_response_tasks,
                return_exceptions=True,
            )
        self._original_response_tasks.clear()
        self._original_candidates.clear()
        self._original_candidate_generation = 0
        self._original_candidate_event.clear()
        self._original_response_sequence = 0
        self._original_capture_decisions.clear()
        self._original_capture_negative_generations.clear()
        if self._original_response_page is not None and self._original_response_page is not page:
            try:
                self._original_response_page.remove_listener(
                    "response", self._handle_original_response
                )
            except (PlaywrightError, AttributeError):
                pass
            try:
                for pattern in self.original_response_route_patterns:
                    await self._original_response_page.unroute(
                        pattern,
                        self._handle_original_route,
                    )
            except (PlaywrightError, AttributeError):
                pass
        if self._original_response_page is not page:
            page.on("response", self._handle_original_response)
            for pattern in self.original_response_route_patterns:
                await page.route(pattern, self._handle_original_route)
            self._original_response_page = page

    @staticmethod
    def _is_original_response(response: object) -> bool:
        """Limit body observation to BookWalker's page-image response host."""

        url = str(getattr(response, "url", ""))
        parsed = urlparse(url)
        host = (parsed.hostname or "").lower()
        is_trial_or_free_epub = (
            host.startswith("viewer-epubs") and host.endswith(".bookwalker.jp")
        )
        is_purchased_epub = host == "bw-bv-epubs.bookwalker.jp"
        if not (is_trial_or_free_epub or is_purchased_epub):
            return False
        request = getattr(response, "request", None)
        resource_type = getattr(request, "resource_type", None)
        if resource_type not in {None, "", "xhr", "fetch", "image"}:
            return False
        try:
            headers = getattr(response, "headers", {}) or {}
            content_type = str(headers.get("content-type", "")).split(";", 1)[0].lower()
        except Exception:  # noqa: BLE001 - a response without headers is ignorable
            content_type = ""
        path = parsed.path.lower()
        return content_type == "image/jpeg" or "jpeg" in path or path.endswith(
            (".jpg", ".jpe")
        )

    def _handle_original_response(self, response: object) -> None:
        if not self._is_original_response(response):
            return
        if len(self._original_response_tasks) >= self.original_response_task_limit:
            return
        task = asyncio.create_task(self._read_original_response(response))
        self._original_response_tasks.add(task)
        task.add_done_callback(self._original_response_tasks.discard)

    async def _handle_original_route(self, route: object) -> None:
        """Read eligible response bodies while fulfilling the same response."""

        try:
            response = await route.fetch()  # type: ignore[attr-defined]
        except Exception:  # noqa: BLE001 - allow the browser's normal request path
            try:
                await route.continue_()  # type: ignore[attr-defined]
            except Exception:  # noqa: BLE001
                return
            return

        try:
            if self._is_original_response(response):
                body = await response.body()
                self._store_original_response_body(response, body)
            await route.fulfill(response=response)  # type: ignore[attr-defined]
        except Exception:  # noqa: BLE001 - body capture must not break the viewer
            try:
                await route.fulfill(response=response)  # type: ignore[attr-defined]
            except Exception:  # noqa: BLE001
                try:
                    await route.continue_()  # type: ignore[attr-defined]
                except Exception:  # noqa: BLE001
                    return

    async def _read_original_response(self, response: object) -> None:
        try:
            status = int(getattr(response, "status", 200))
            if status < 200 or status >= 300:
                return
            headers = getattr(response, "headers", {}) or {}
            content_length = headers.get("content-length")
            if content_length is not None:
                try:
                    if int(content_length) > MAX_RESPONSE_BODY_BYTES:
                        return
                except (TypeError, ValueError):
                    pass
            body = await response.body()  # type: ignore[attr-defined]
            self._store_original_response_body(response, body)
        except Exception:  # noqa: BLE001 - body failure must use native fallback
            return

    def _store_original_response_body(self, response: object, body: object) -> None:
        if not isinstance(body, bytes) or len(body) > MAX_RESPONSE_BODY_BYTES:
            return
        self._original_response_sequence += 1
        candidate = candidate_from_jpeg(
            body,
            url=str(getattr(response, "url", "")),
            sequence=self._original_response_sequence,
        )
        if candidate is not None and self._original_candidates.add(candidate):
            self._original_candidate_generation += 1
            self._original_candidate_event.set()

    async def _wait_for_original_candidate_work(
        self,
        baseline_generation: int,
    ) -> bool:
        """Wait briefly only when an eligible response task is still pending."""

        if self._original_candidate_generation != baseline_generation:
            return True
        pending_tasks = tuple(
            task for task in self._original_response_tasks if not task.done()
        )
        if not pending_tasks:
            return False

        self._original_candidate_event.clear()
        if self._original_candidate_generation != baseline_generation:
            self._original_candidate_event.set()
            return True

        deadline = (
            asyncio.get_running_loop().time()
            + self.original_capture_retry_interval_ms / 1000
        )
        event_task = asyncio.create_task(self._original_candidate_event.wait())
        try:
            while True:
                if self._original_candidate_generation != baseline_generation:
                    return True
                remaining_tasks = tuple(
                    task for task in pending_tasks if not task.done()
                )
                if not remaining_tasks:
                    return False
                timeout = deadline - asyncio.get_running_loop().time()
                if timeout <= 0:
                    return False
                await asyncio.wait(
                    (*remaining_tasks, event_task),
                    timeout=timeout,
                    return_when=asyncio.FIRST_COMPLETED,
                )
                if self._original_candidate_generation != baseline_generation:
                    return True
                if event_task.done():
                    # The event is only expected to be set with a generation
                    # change. Re-arm it defensively if an external test or
                    # future helper signals it without adding a candidate.
                    self._original_candidate_event.clear()
                    event_task = asyncio.create_task(
                        self._original_candidate_event.wait()
                    )
        finally:
            if not event_task.done():
                event_task.cancel()
            await asyncio.gather(event_task, return_exceptions=True)
        return self._original_candidate_generation != baseline_generation

    async def _capture_original_jpegs(
        self,
        page: Page,
        native_captures: tuple[CaptureResult, ...],
    ) -> tuple[CaptureResult, ...] | None:
        """Return JPEGs only when every visible native part matches uniquely."""

        matcher_started = time.perf_counter()
        capture_debug = self._capture_debug["bookwalker_capture"]
        timing = capture_debug["timing_ms"]
        for key in (
            "original_native_signature_ms",
            "original_candidate_signature_ms",
            "original_match_scan_ms",
            "original_retry_wait_ms",
            "original_total_ms",
        ):
            timing[key] = 0.0
        original_debug = _original_match_debug_defaults()
        capture_debug["original_match"] = original_debug
        original_debug.update({
            "original_pending_task_count_at_start": sum(
                not task.done() for task in self._original_response_tasks
            ),
            "original_candidate_count_at_start": len(self._original_candidates),
            "original_candidate_generation_start": self._original_candidate_generation,
        })
        try:
            native_signature_started = time.perf_counter()
            native_signatures = tuple(
                [
                    await image_signature(page, capture.data, "image/png")
                    for capture in native_captures
                ]
            )
            timing["original_native_signature_ms"] = _elapsed_ms(
                native_signature_started
            )
            if any(signature is None for signature in native_signatures):
                return None

            decision_key = tuple(
                (capture.width, capture.height, signature)
                for capture, signature in zip(
                    native_captures, native_signatures, strict=True
                )
                if signature is not None
            )
            if len(decision_key) != len(native_captures):
                return None
            if decision_key in self._original_capture_decisions:
                selected_hashes = self._original_capture_decisions[decision_key]
                if selected_hashes is None:
                    if (
                        self._original_capture_negative_generations.get(decision_key)
                        == self._original_candidate_generation
                    ):
                        return None
                    self._original_capture_decisions.pop(decision_key, None)
                    self._original_capture_negative_generations.pop(
                        decision_key, None
                    )
                    selected_hashes = None
                if selected_hashes is not None:
                    by_hash = {
                        candidate.sha256: candidate
                        for candidate in self._original_candidates.values()
                    }
                    selected = [by_hash.get(sha256) for sha256 in selected_hashes]
                    if any(candidate is None for candidate in selected):
                        return None
                    resolved = tuple(
                        candidate for candidate in selected if candidate is not None
                    )
                    if len(resolved) != len(selected):
                        return None
                    return tuple(candidate_capture(candidate) for candidate in resolved)

            for attempt in range(self.original_capture_attempts):
                original_debug["original_attempt_count"] = attempt + 1
                attempt_generation = self._original_candidate_generation
                candidates = self._original_candidates.values()
                selected = []
                match_scan_started = time.perf_counter()
                candidate_signature_elapsed = 0.0
                for capture, native_signature in zip(
                    native_captures, native_signatures, strict=True
                ):
                    matches = []
                    for candidate in candidates:
                        if (candidate.width, candidate.height) != (
                            capture.width,
                            capture.height,
                        ):
                            continue
                        if candidate.signature is None:
                            candidate_signature_started = time.perf_counter()
                            candidate.signature = await image_signature(
                                page, candidate.data, candidate.mime_type
                            )
                            candidate_signature_elapsed += (
                                time.perf_counter() - candidate_signature_started
                            ) * 1000
                        if candidate.signature == native_signature:
                            matches.append(candidate)
                    if len(matches) != 1:
                        selected = []
                        break
                    selected.append(matches[0])

                match_scan_elapsed = (
                    time.perf_counter() - match_scan_started
                ) * 1000
                timing["original_candidate_signature_ms"] += round(
                    candidate_signature_elapsed, 2
                )
                timing["original_match_scan_ms"] += round(
                    max(0.0, match_scan_elapsed - candidate_signature_elapsed), 2
                )

                if selected and len({candidate.sha256 for candidate in selected}) == len(
                    selected
                ):
                    self._original_capture_decisions[decision_key] = tuple(
                        candidate.sha256 for candidate in selected
                    )
                    self._original_capture_negative_generations.pop(
                        decision_key, None
                    )
                    return tuple(candidate_capture(candidate) for candidate in selected)

                if self._original_candidate_generation != attempt_generation:
                    continue
                if attempt >= self.original_capture_attempts - 1:
                    break

                pending_task_count = sum(
                    not task.done() for task in self._original_response_tasks
                )
                if not pending_task_count:
                    break
                original_debug["original_retry_wait_count"] += 1
                retry_started = time.perf_counter()
                await self._wait_for_original_candidate_work(attempt_generation)
                timing["original_retry_wait_ms"] += _elapsed_ms(retry_started)
                if self._original_candidate_generation != attempt_generation:
                    continue
                break

            self._original_capture_decisions[decision_key] = None
            self._original_capture_negative_generations[decision_key] = (
                self._original_candidate_generation
            )
        except Exception:  # noqa: BLE001 - original capture is an optimization
            return None
        finally:
            timing["original_total_ms"] = _elapsed_ms(matcher_started)
            for key in (
                "original_candidate_signature_ms",
                "original_match_scan_ms",
                "original_retry_wait_ms",
            ):
                timing[key] = round(timing[key], 2)
            original_debug["original_candidate_count_at_end"] = len(
                self._original_candidates
            )
            original_debug["original_candidate_generation_end"] = (
                self._original_candidate_generation
            )

    def _reset_capture_debug(self) -> None:
        self._capture_debug = {
            "bookwalker_capture": {
                "returned_path": "native_png",
                "timing_ms": _capture_timing_defaults(),
                "original_match": _original_match_debug_defaults(),
                "lossless_shadow": {
                    "attempted": False,
                    "spread_ready": False,
                    "output_enabled": self.lossless_jpeg_output_enabled,
                    "output_used": False,
                    "final_pixel_verify_enabled": self.final_pixel_verify_enabled,
                    "final_pixel_compare_performed": False,
                    "parts": [],
                },
            }
        }

    @staticmethod
    def _shadow_part_defaults(
        candidate_count_total: int = 0,
        *,
        final_pixel_verify_enabled: bool = False,
    ) -> dict[str, Any]:
        return {
            "candidate_count_total": candidate_count_total,
            "candidate_count_dimension_match": 0,
            "candidate_count_signature_match": 0,
            "candidate_count_full_exact": 0,
            "full_resolution_comparison_count": 0,
            "mapping_proven": False,
            "raw_jpeg_exact": False,
            "jpeg_supported": False,
            "strict_mcu_aligned": False,
            "coefficient_exact": False,
            "component_quantization_selectors_equal": False,
            "final_pixel_verify_enabled": final_pixel_verify_enabled,
            "final_pixel_compare_performed": False,
            "native_pixel_exact": None,
            "cropped_chain_pixel_exact": None,
            "cropped_chain_pixel_comparison": None,
            "final_pixel_comparison_mode": None,
            "reconstructed_dimensions_match": False,
            "reconstructed_source_dimensions_match": False,
            "reconstructed_visible_dimensions_match": False,
            "coded_dimensions": None,
            "visible_dimensions": None,
            "tile_dimensions_uniform": None,
            "tile_dimension_variants": [],
            "mapping_source": None,
            "mapping_id": None,
            "selected_mapping_id": None,
            "segment_clear_operation_index": None,
            "segment_first_tile_operation_index": None,
            "segment_last_tile_operation_index": None,
            "segment_tile_count": 0,
            "segment_expected_tile_count": None,
            "segment_overflow": False,
            "completed_mapping_evicted": False,
            "renderer_geometry_classification": "GEOMETRY_UNAVAILABLE",
            "mapping_provenance": None,
            "renderer_canvas_id": None,
            "source_canvas_id": None,
            "upstream_mapping_id": None,
            "provenance_copy_operation_index": None,
            "provenance_source_canvas_id": None,
            "provenance_target_canvas_id": None,
            "provenance_source_dimensions": None,
            "provenance_target_dimensions": None,
            "provenance_scale_x": None,
            "provenance_scale_y": None,
        }

    async def _browser_pixel_exact(
        self,
        page: Page,
        reconstructed: bytes,
        native: bytes,
    ) -> dict[str, object]:
        encoded_reconstructed = base64.b64encode(reconstructed).decode("ascii")
        encoded_native = base64.b64encode(native).decode("ascii")
        try:
            result = await page.evaluate(
                _PIXEL_EXACT_COMPARISON_SCRIPT,
                {
                    "reconstructed": f"data:image/jpeg;base64,{encoded_reconstructed}",
                    "native": f"data:image/png;base64,{encoded_native}",
                },
            )
        except Exception:  # noqa: BLE001 - shadow validation must fail closed
            return {"available": False, "exact": False, "reason": "browser comparison failed"}
        return result if isinstance(result, dict) else {
            "available": False,
            "exact": False,
            "reason": "browser comparison returned invalid data",
        }

    async def _browser_scaled_source_pixel_exact(
        self,
        page: Page,
        reconstructed: bytes,
        native: bytes,
        *,
        source_rect: dict[str, float],
        destination: dict[str, float],
        target_dimensions: tuple[int, int],
        image_smoothing_enabled: bool | None,
        image_smoothing_quality: str | None,
    ) -> dict[str, object]:
        """Compare a source-native JPEG after the proven one-hop scale."""

        if (
            image_smoothing_enabled is None
            or image_smoothing_quality not in {"low", "medium", "high"}
        ):
            return {
                "available": False,
                "exact": False,
                "reason": "smoothing metadata unavailable",
            }
        encoded_reconstructed = base64.b64encode(reconstructed).decode("ascii")
        encoded_native = base64.b64encode(native).decode("ascii")
        try:
            result = await page.evaluate(
                _SCALED_SOURCE_PIXEL_EXACT_COMPARISON_SCRIPT,
                {
                    "reconstructed": f"data:image/jpeg;base64,{encoded_reconstructed}",
                    "native": f"data:image/png;base64,{encoded_native}",
                    "sourceRect": source_rect,
                    "destination": destination,
                    "targetDimensions": {
                        "width": target_dimensions[0],
                        "height": target_dimensions[1],
                    },
                    "imageSmoothingEnabled": image_smoothing_enabled,
                    "imageSmoothingQuality": image_smoothing_quality,
                },
            )
        except Exception:  # noqa: BLE001 - diagnostic validation fails closed
            return {
                "available": False,
                "exact": False,
                "reason": "browser comparison failed",
            }
        return result if isinstance(result, dict) else {
            "available": False,
            "exact": False,
            "reason": "browser comparison returned invalid data",
        }

    async def _materialize_canvas_snapshot(
        self, page: Page, snapshot_id: str | None
    ) -> str | None:
        if not snapshot_id:
            return None
        try:
            result = await page.evaluate(
                """
                snapshotId => window.__bookwalkerMaterializeNativeSourceCrop?.({
                  sourceConstructor: 'HTMLCanvasElement', snapshotId,
                }) || null
                """,
                snapshot_id,
            )
        except Exception:  # noqa: BLE001 - required provenance gate fails closed
            return None
        if not isinstance(result, dict) or result.get("error") is not None:
            return None
        data_url = result.get("dataUrl")
        return data_url if isinstance(data_url, str) and data_url else None

    async def _browser_cropped_one_hop_pixel_exact(
        self,
        page: Page,
        reconstructed: bytes,
        selected_call: dict[str, Any],
        provenance_candidate: Any,
        mapping: Any,
        source_snapshot: str | None,
    ) -> dict[str, object]:
        """Replay the proven A->B copy and selected B->renderer ROI."""

        intermediate = selected_call.get("fullSourcePng")
        final_target = selected_call.get("targetCropPng")
        final_source_rect = selected_call.get("sourceRect")
        final_destination = selected_call.get("destination")
        if (
            not isinstance(source_snapshot, str)
            or not isinstance(intermediate, str)
            or not isinstance(final_target, str)
        ):
            return {"available": False, "exact": False, "reason": "immutable chain snapshot unavailable"}
        if not isinstance(final_source_rect, dict) or not isinstance(final_destination, dict):
            return {"available": False, "exact": False, "reason": "selected renderer geometry unavailable"}
        final_canvas_width = selected_call.get("canvasWidth")
        final_canvas_height = selected_call.get("canvasHeight")
        if (
            not isinstance(final_canvas_width, int)
            or isinstance(final_canvas_width, bool)
            or not isinstance(final_canvas_height, int)
            or isinstance(final_canvas_height, bool)
            or final_canvas_width <= 0
            or final_canvas_height <= 0
        ):
            return {
                "available": False,
                "exact": False,
                "reason": "selected renderer backing-canvas dimensions unavailable",
            }
        copy_smoothing_enabled = provenance_candidate.image_smoothing_enabled
        copy_smoothing_quality = provenance_candidate.image_smoothing_quality
        final_smoothing_enabled = selected_call.get("imageSmoothingEnabled")
        final_smoothing_quality = selected_call.get("imageSmoothingQuality")
        if copy_smoothing_enabled is None or copy_smoothing_quality not in {"low", "medium", "high"}:
            return {"available": False, "exact": False, "reason": "copy smoothing metadata unavailable"}
        if not isinstance(final_smoothing_enabled, bool) or final_smoothing_quality not in {"low", "medium", "high"}:
            return {"available": False, "exact": False, "reason": "renderer smoothing metadata unavailable"}
        encoded = base64.b64encode(reconstructed).decode("ascii")
        try:
            result = await page.evaluate(
                _CROPPED_ONE_HOP_PIXEL_EXACT_COMPARISON_SCRIPT,
                {
                    "reconstructed": f"data:image/jpeg;base64,{encoded}",
                    "sourceSnapshot": source_snapshot,
                    "intermediate": intermediate,
                    "finalTarget": final_target,
                    "copySourceRect": provenance_candidate.source_rect,
                    "copyDestination": provenance_candidate.destination,
                    "finalSourceRect": final_source_rect,
                    "finalDestination": final_destination,
                    "finalCanvasDimensions": {
                        "width": final_canvas_width,
                        "height": final_canvas_height,
                    },
                    "intermediateDimensions": {
                        "width": provenance_candidate.target_dimensions[0],
                        "height": provenance_candidate.target_dimensions[1],
                    },
                    "copySmoothingEnabled": copy_smoothing_enabled,
                    "copySmoothingQuality": copy_smoothing_quality,
                    "finalSmoothingEnabled": final_smoothing_enabled,
                    "finalSmoothingQuality": final_smoothing_quality,
                },
            )
        except Exception:  # noqa: BLE001 - provenance validation fails closed
            return {"available": False, "exact": False, "reason": "browser chain comparison failed"}
        return result if isinstance(result, dict) else {
            "available": False,
            "exact": False,
            "reason": "browser chain comparison returned invalid data",
        }

    async def _p4b_current_roi_atomic_proof(
        self,
        page: Page,
        selected_call: dict[str, Any],
        initial_anchor: dict[str, Any] | None,
        renderer_handle: Any | None = None,
        proof_trace_epoch: Any | None = None,
    ) -> dict[str, Any]:
        """Check the strict cropped proof against the live DOM in one task."""
        selected_source = selected_call.get("source")
        source_canvas_id = (
            selected_source.get("canvasId")
            if isinstance(selected_source, dict)
            else selected_call.get("sourceCanvasId")
        )
        operation_index = selected_call.get("traceOperationIndex")
        selected_trace_epoch = selected_call.get("traceEpoch")
        if (
            not isinstance(initial_anchor, dict)
            or not isinstance(operation_index, int)
            or renderer_handle is None
            or not isinstance(selected_trace_epoch, int)
            or isinstance(selected_trace_epoch, bool)
            or selected_trace_epoch <= 0
            or not isinstance(proof_trace_epoch, int)
            or isinstance(proof_trace_epoch, bool)
            or proof_trace_epoch <= 0
            or selected_trace_epoch != proof_trace_epoch
        ):
            return {"available": False, "exact": False, "reason": "initial P4B anchor unavailable"}
        if (
            self._initial_content_id is None
            or initial_anchor.get("bookIdentity") != self._initial_content_id
            or initial_anchor.get("traceEpoch") != selected_trace_epoch
        ):
            return {"available": False, "exact": False, "reason": "authorized book identity unavailable"}
        expected_selected = initial_anchor.get("selected")
        if not isinstance(expected_selected, dict):
            return {"available": False, "exact": False, "reason": "initial selected B anchor unavailable"}
        actual_source = selected_call.get("source")
        actual_source_content_version = selected_call.get("sourceContentVersion")
        if isinstance(actual_source, dict) and actual_source_content_version is None:
            actual_source_content_version = actual_source.get("contentVersion")
        actual_selected = {
            "operationIndex": operation_index,
            "traceEpoch": selected_trace_epoch,
            "sourceId": selected_call.get("sourceId"),
            "sourceCanvasId": source_canvas_id,
            "sourceContentVersion": actual_source_content_version,
            "fullSourceSnapshotId": selected_call.get("fullSourceSnapshotId"),
            "targetSnapshotId": selected_call.get("targetSnapshotId"),
            "targetContentVersionAfter": selected_call.get("targetContentVersionAfter"),
            "sourceRect": selected_call.get("sourceRect"),
            "destination": selected_call.get("destination"),
        }
        selected_fields = tuple(actual_selected)
        if any(
            actual_selected[field] is None
            or expected_selected.get(field) is None
            or actual_selected[field] != expected_selected.get(field)
            for field in selected_fields
        ):
            return {"available": False, "exact": False, "reason": "selected native snapshot identity mismatch"}
        expected = {
            "traceId": initial_anchor.get("traceId"),
            "actualCanvasId": initial_anchor.get("actualCanvasId"),
            "traceEpoch": initial_anchor.get("traceEpoch"),
            "operationIndex": operation_index,
            "sourceId": expected_selected.get("sourceId"),
            "sourceCanvasId": source_canvas_id,
            "selectedTraceEpoch": expected_selected.get("traceEpoch"),
            "sourceContentVersion": expected_selected.get("sourceContentVersion"),
            "fullSourceSnapshotId": expected_selected.get("fullSourceSnapshotId"),
            "targetSnapshotId": expected_selected.get("targetSnapshotId"),
            "targetContentVersionAfter": expected_selected.get(
                "targetContentVersionAfter"
            ),
            "sourceRect": expected_selected.get("sourceRect"),
            "destination": expected_selected.get("destination"),
        }
        if not expected.get("targetSnapshotId"):
            return {"available": False, "exact": False, "reason": "immutable renderer ROI unavailable"}
        try:
            result = await page.evaluate(
                _BOOKWALKER_P4B_CURRENT_ROI_ANCHOR_SCRIPT,
                {
                    "expected": expected,
                    "initialAnchor": initial_anchor,
                    "destination": selected_call.get("destination"),
                    "originalElement": renderer_handle,
                },
            )
        except (PlaywrightError, PlaywrightTimeoutError, TimeoutError, TypeError):
            return {"available": False, "exact": False, "reason": "atomic current ROI comparison failed"}
        return result if isinstance(result, dict) else {
            "available": False,
            "exact": False,
            "reason": "atomic current ROI comparison returned invalid data",
        }

    async def _capture_direct_one_hop_original_jpeg(
        self,
        page: Page,
        canvas: Locator,
        selected_draw_call: dict[str, Any],
        selection_geometry_state: dict[str, Any],
        renderer_handle: Any | None = None,
    ) -> tuple[CaptureResult, ...] | None:
        """Return a byte-preserving JPEG for one verified cover draw chain.

        This path is intentionally independent of tiled reconstruction.  The
        page hook retains only bounded canvas snapshots and actual object
        references; this method materializes and compares them after drawing.
        Any missing identity, mutation, ambiguity, or pixel mismatch falls
        through to the existing native PNG/reconstruction paths.
        """

        direct_debug: dict[str, Any] = {
            "attempted": True,
            "accepted": False,
            "reason": "no direct one-hop record",
            "candidate_count": 0,
            "exact_candidate_count": 0,
            "records": [],
            "selected_native_draw": (
                {
                    "trace_operation_index": selected_draw_call.get("traceOperationIndex"),
                    "canvas_id": selected_draw_call.get("canvasId"),
                    "source_id": selected_draw_call.get("sourceId"),
                    "source_rect": selected_draw_call.get("sourceRect"),
                    "destination": selected_draw_call.get("destination"),
                }
                if isinstance(selected_draw_call, dict)
                else None
            ),
        }
        self._capture_debug["bookwalker_capture"]["direct_original_jpeg"] = direct_debug
        direct_canvas = renderer_handle or canvas
        try:
            records = await direct_canvas.evaluate(
                "element => window.__bookwalkerMaterializeDirectOneHop?.(element) || []"
            )
        except (
            PlaywrightError,
            PlaywrightTimeoutError,
            TimeoutError,
            TypeError,
        ):
            direct_debug["reason"] = "direct one-hop materialization failed"
            return None
        if not isinstance(records, list):
            direct_debug["reason"] = "direct one-hop records invalid"
            return None
        direct_debug["record_count"] = len(records)
        candidates = tuple(self._original_candidates.values())
        direct_debug["candidate_count"] = len(candidates)
        direct_debug["selection_geometry_state"] = (
            {
                "token": selection_geometry_state.get("token"),
                "geometry_version": selection_geometry_state.get("geometryVersion"),
                "geometry_history_incomplete": selection_geometry_state.get(
                    "geometryHistoryIncomplete"
                ),
                "geometry_history_limit": selection_geometry_state.get(
                    "geometryHistoryLimit"
                ),
                "geometry_ledger_length": selection_geometry_state.get(
                    "geometryLedgerLength"
                ),
                "geometry_history_evictions": selection_geometry_state.get(
                    "geometryHistoryEvictions"
                ),
            }
            if isinstance(selection_geometry_state, dict)
            else None
        )
        selected_trace_operation = selected_draw_call.get("traceOperationIndex")
        if not isinstance(selected_trace_operation, int):
            direct_debug["reason"] = "selected native draw operation unavailable"
            return None
        selection_token = (
            selection_geometry_state.get("token")
            if isinstance(selection_geometry_state, dict) else None
        )
        selection_geometry_version = (
            selection_geometry_state.get("geometryVersion")
            if isinstance(selection_geometry_state, dict) else None
        )
        if (
            not isinstance(selection_token, str)
            or not isinstance(selection_geometry_version, int)
            or not isinstance(selection_geometry_state, dict)
            or selection_geometry_state.get("geometryHistoryIncomplete") is True
        ):
            direct_debug["reason"] = (
                "direct cover geometry history incomplete"
                if isinstance(selection_geometry_state, dict)
                and selection_geometry_state.get("geometryHistoryIncomplete") is True
                else "direct cover geometry selection state unavailable"
            )
            return None
        latest_renderer_operation = max(
            (
                int((item.get("renderer") or {}).get("operationIndex"))
                for item in records
                if isinstance(item, dict)
                and isinstance(item.get("renderer"), dict)
                and item.get("renderer", {}).get("sameCurrentObject") is True
                and isinstance(item.get("renderer", {}).get("operationIndex"), int)
            ),
            default=0,
        )
        for record in records:
            if not isinstance(record, dict):
                continue
            copy_record = record.get("copy")
            renderer_record = record.get("renderer")
            if not isinstance(copy_record, dict) or not isinstance(renderer_record, dict):
                continue
            row: dict[str, Any] = {
                "token": record.get("token"),
                "page_url": record.get("pageUrl"),
                "page_counter": record.get("pageCounter"),
                "copy_operation": copy_record.get("operationIndex"),
                "renderer_operation": renderer_record.get("operationIndex"),
                "renderer_geometry_version": renderer_record.get("geometryVersion"),
                "current_geometry_version": renderer_record.get("currentGeometryVersion"),
                "geometry_history_incomplete": renderer_record.get(
                    "geometryHistoryIncomplete"
                ),
                "same_current_object": renderer_record.get("sameCurrentObject") is True,
                "renderer_mutation": renderer_record.get("mutation"),
                "renderer_last_mutation": renderer_record.get("lastMutation"),
                "renderer_unsafe_mutation": renderer_record.get("unsafeMutation"),
                "renderer_invalidated": renderer_record.get("invalidated"),
                "renderer_invalidation_operation": renderer_record.get(
                    "invalidationOperationIndex"
                ),
                "renderer_first_hard_invalid": renderer_record.get("firstHardInvalid"),
                "renderer_non_intersecting_draw": renderer_record.get(
                    "nonIntersectingDraw"
                ),
                "source_id": copy_record.get("sourceId"),
                "source_dimensions": [
                    (copy_record.get("sourceInfo") or {}).get("width"),
                    (copy_record.get("sourceInfo") or {}).get("height"),
                ],
            }
            direct_debug["records"].append(row)
            if record.get("token") != record.get("frameToken"):
                row["reason"] = "frame token mismatch"
                continue
            if record.get("token") != record.get("currentToken"):
                row["reason"] = "stale direct hook token"
                continue
            if renderer_record.get("sameCurrentObject") is not True:
                row["reason"] = "renderer target is not current DOM canvas"
                continue
            if renderer_record.get("operationIndex") != selected_trace_operation:
                row["reason"] = "renderer operation is not the selected native draw"
                continue
            selected_canvas_id = selected_draw_call.get("canvasId")
            selected_source_id = selected_draw_call.get("sourceId")
            selected_source_rect = selected_draw_call.get("sourceRect")
            selected_destination = selected_draw_call.get("destination")
            if (
                not isinstance(selected_canvas_id, str)
                or not isinstance(selected_source_id, str)
                or renderer_record.get("targetInfo", {}).get("canvasId")
                != selected_canvas_id
                or renderer_record.get("sourceInfo", {}).get("sourceId")
                != selected_source_id
                or renderer_record.get("sourceRect") != selected_source_rect
                or renderer_record.get("destination") != selected_destination
            ):
                row["reason"] = "selected native draw identity or geometry mismatch"
                continue
            page_counter = record.get("pageCounter")
            if page_counter is None:
                row["reason"] = "direct cover page counter unavailable"
                continue
            page_number, _page_id = self.parse_page_counter(str(page_counter))
            if page_number != 1:
                row["reason"] = "direct cover record is not page one"
                continue
            if renderer_record.get("geometryHistoryIncomplete") is True:
                row["reason"] = "direct cover geometry history incomplete"
                continue
            if (
                record.get("token") != selection_token
                or renderer_record.get("geometryVersion") != selection_geometry_version
                or renderer_record.get("currentGeometryVersion") != selection_geometry_version
            ):
                row["reason"] = "direct cover geometry changed before validation"
                continue
            if renderer_record.get("geometryVersion") != renderer_record.get(
                "currentGeometryVersion"
            ):
                row["reason"] = "renderer geometry changed during validation"
                continue
            if renderer_record.get("operationIndex") != latest_renderer_operation:
                row["reason"] = "superseded by newer current renderer anchor"
                continue
            if record.get("currentConnected") is not True:
                row["reason"] = "current DOM canvas is disconnected"
                continue
            if renderer_record.get("invalidated") is True:
                row["reason"] = "renderer record was invalidated after selection"
                continue
            mutation = renderer_record.get("mutation")
            allowed_pixel_mutations = {
                "drawImage",
                "save",
                "restore",
                "fillRect",
                "putImageData",
                "fillText",
                "strokeText",
                "fill",
                "stroke",
            }
            if renderer_record.get("unsafeMutation") is not None:
                row["reason"] = "renderer post-draw state or reset mutation"
                continue
            if (
                mutation is not None
                and renderer_record.get("lastMutation") not in allowed_pixel_mutations
            ):
                row["reason"] = "renderer post-draw unsupported mutation"
                continue
            if (
                mutation == "drawImage"
                and renderer_record.get("nonIntersectingDraw") is not True
            ):
                row["reason"] = "renderer follow-up drawImage is not proven non-intersecting"
                continue
            if not self._direct_draw_is_safe(copy_record) or not self._direct_draw_is_safe(
                renderer_record
            ):
                row["reason"] = "direct draw composition or transform is unsafe"
                continue
            if not isinstance(copy_record.get("operationIndex"), int) or not isinstance(
                renderer_record.get("operationIndex"), int
            ) or copy_record["operationIndex"] >= renderer_record["operationIndex"]:
                row["reason"] = "direct operation order is invalid"
                continue
            if not isinstance(copy_record.get("sourceSnapshot"), str) or not isinstance(
                copy_record.get("intermediate"), str
            ) or not isinstance(renderer_record.get("sourceB"), str):
                row["reason"] = "immutable A/B snapshot unavailable"
                continue
            if not isinstance(renderer_record.get("targetSnapshot"), str) or not isinstance(
                renderer_record.get("current"), str
            ):
                row["reason"] = "immutable renderer/current snapshot unavailable"
                continue
            if copy_record.get("targetContentVersionAfter") != renderer_record.get(
                "sourceContentVersion"
            ):
                row["reason"] = "A/B content version join unavailable"
                continue
            # A known post-draw pixel write may be outside the selected ROI.
            # The immediate immutable ROI versus the current ROI comparison
            # below is the authority for that case.  State-changing and
            # reset/clip operations remain fail-closed above.
            source_info = copy_record.get("sourceInfo")
            if not isinstance(source_info, dict) or source_info.get("constructor") != "ImageBitmap":
                row["reason"] = "direct source is not ImageBitmap"
                continue
            source_id = source_info.get("sourceId")
            if not isinstance(source_id, str):
                row["reason"] = "ImageBitmap source identity unavailable"
                continue
            source_dimensions = (
                source_info.get("width"),
                source_info.get("height"),
            )
            dimension_candidates = tuple(
                candidate
                for candidate in candidates
                if (candidate.width, candidate.height) == source_dimensions
            )
            if not dimension_candidates:
                row["reason"] = "no JPEG candidate with source dimensions"
                continue
            exact_candidates = []
            for candidate in dimension_candidates:
                match = await imagebitmap_pixel_exact_match(
                    page,
                    candidate.data,
                    source_id,
                    candidate.mime_type,
                )
                if isinstance(match, dict) and match.get("exact") is True:
                    exact_candidates.append(candidate)
            row["exact_candidate_count"] = len(exact_candidates)
            direct_debug["exact_candidate_count"] += len(exact_candidates)
            if len(exact_candidates) != 1:
                row["reason"] = "direct JPEG candidate is not unique"
                continue
            candidate = exact_candidates[0]
            encoded = base64.b64encode(candidate.data).decode("ascii")
            try:
                comparison = await page.evaluate(
                    _DIRECT_ONE_HOP_PIXEL_EXACT_COMPARISON_SCRIPT,
                    {
                        "candidate": f"data:image/jpeg;base64,{encoded}",
                        "sourceSnapshot": copy_record["sourceSnapshot"],
                        "intermediate": copy_record["intermediate"],
                        "sourceB": renderer_record["sourceB"],
                        "targetSnapshot": renderer_record["targetSnapshot"],
                        "current": renderer_record["current"],
                        "copySourceRect": copy_record.get("sourceRect"),
                        "copyDestination": copy_record.get("destination"),
                        "rendererSourceRect": renderer_record.get("sourceRect"),
                        "rendererDestination": renderer_record.get("destination"),
                        "intermediateDimensions": {
                            "width": (copy_record.get("targetInfo") or {}).get("width"),
                            "height": (copy_record.get("targetInfo") or {}).get("height"),
                        },
                        "rendererDimensions": {
                            "width": (renderer_record.get("targetInfo") or {}).get("width"),
                            "height": (renderer_record.get("targetInfo") or {}).get("height"),
                        },
                        "copySmoothingEnabled": copy_record.get("imageSmoothingEnabled"),
                        "copySmoothingQuality": copy_record.get("imageSmoothingQuality"),
                        "rendererSmoothingEnabled": renderer_record.get("imageSmoothingEnabled"),
                        "rendererSmoothingQuality": renderer_record.get("imageSmoothingQuality"),
                    },
                )
            except (
                PlaywrightError,
                PlaywrightTimeoutError,
                TimeoutError,
                TypeError,
                ValueError,
            ):
                row["reason"] = "direct output-equivalence comparison failed"
                continue
            row["comparison"] = comparison
            if not isinstance(comparison, dict) or comparison.get("exact") is not True:
                row["reason"] = "direct output-equivalence mismatch"
                continue
            try:
                current_state = await direct_canvas.evaluate(
                    """
                    element => window.__bookwalkerDirectOneHopCurrentState?.(element) || null
                    """
                )
            except (PlaywrightError, PlaywrightTimeoutError, TimeoutError, TypeError):
                current_state = None
            states = current_state.get("records") if isinstance(current_state, dict) else None
            stable = isinstance(states, list) and any(
                isinstance(state, dict)
                and state.get("operationIndex") == renderer_record.get("operationIndex")
                and state.get("unsafeMutation") is None
                and state.get("lastMutation") == renderer_record.get("lastMutation")
                and state.get("currentContentVersion") == renderer_record.get(
                    "currentContentVersion"
                )
                for state in states
            )
            if (
                not isinstance(current_state, dict)
                or current_state.get("token") != record.get("currentToken")
                or current_state.get("pageUrl") != record.get("pageUrl")
                or current_state.get("connected") is not True
                or current_state.get("activeOperationIndex")
                != renderer_record.get("operationIndex")
                or current_state.get("geometryVersion")
                != renderer_record.get("currentGeometryVersion")
                or current_state.get("geometryHistoryIncomplete") is True
                or current_state.get("token") != selection_token
                or current_state.get("geometryVersion") != selection_geometry_version
                or current_state.get("pageCounter") != record.get("pageCounter")
                or self.parse_page_counter(str(current_state.get("pageCounter") or ""))[0] != 1
                or not stable
            ):
                row["reason"] = "direct hook changed during validation"
                continue
            row["reason"] = "direct output-equivalence exact"
            direct_debug.update({
                "accepted": True,
                "reason": "unique raw JPEG and A/B/renderer/current RGBA exact",
                "candidate_sha256": candidate.sha256,
                "source_id": source_id,
            })
            return (candidate_capture(candidate),)
        return None

    @staticmethod
    def _direct_draw_is_safe(record: dict[str, Any]) -> bool:
        transform = record.get("transform")
        return (
            isinstance(transform, dict)
            and all(transform.get(key) == value for key, value in {
                "a": 1, "b": 0, "c": 0, "d": 1, "e": 0, "f": 0,
            }.items())
            and record.get("globalAlpha") == 1
            and record.get("globalCompositeOperation") == "source-over"
            and record.get("filter") == "none"
        )

    async def _evaluate_lossless_reconstruction(
        self,
        page: Page,
        native_captures: tuple[CaptureResult, ...],
        selected_draw_calls: list[dict[str, Any]],
        *,
        p4b_initial_anchor: dict[str, Any] | None = None,
        p4b_renderer_handle: Any | None = None,
    ) -> LosslessReconstructionEvaluation:
        """Evaluate supported source JPEG reconstruction and retain verified captures."""

        evaluation_started = time.perf_counter()
        evaluation_timing = _evaluation_timing_defaults()
        shadow: dict[str, Any] = {
            "attempted": True,
            "spread_ready": False,
            "output_enabled": self.lossless_jpeg_output_enabled,
            "output_used": False,
            "final_pixel_verify_enabled": self.final_pixel_verify_enabled,
            "final_pixel_compare_performed": False,
            "trace_fetch_mode": "selected_completed_mappings_compact_v1",
            "timing_ms": evaluation_timing,
            "parts": [],
            **_trace_payload_stats(None),
        }

        def finish_timing() -> None:
            evaluation_timing["trace_fetch_ms"] = (
                evaluation_timing["selected_trace_fetch_ms"]
                + evaluation_timing["upstream_trace_fetch_ms"]
            )
            evaluation_timing["trace_decode_ms"] = (
                evaluation_timing["selected_trace_decode_ms"]
                + evaluation_timing["upstream_trace_decode_ms"]
            )
            evaluation_timing["evaluation_total"] = _elapsed_ms(evaluation_started)
            measured_keys = (
                "trace_fetch_ms",
                "trace_decode_ms",
                "mapping_analysis",
                "imagebitmap_signature",
                "candidate_signature_total",
                "raw_full_resolution_compare",
                "lossless_reconstruction",
                "final_browser_pixel_compare",
            )
            evaluation_timing["measured_component_total_ms"] = sum(
                evaluation_timing[key] for key in measured_keys
            )
            evaluation_timing["unaccounted_ms"] = (
                evaluation_timing["evaluation_total"]
                - evaluation_timing["measured_component_total_ms"]
            )
            for key, value in evaluation_timing.items():
                evaluation_timing[key] = round(value, 2)
            shadow["lossless_evaluation_total_ms"] = evaluation_timing[
                "evaluation_total"
            ]
        reconstruction_candidates = tuple(
            candidate
            for candidate in self._original_candidates.values()
            if is_reconstruction_jpeg_candidate(candidate)
        )
        if len(selected_draw_calls) != len(native_captures):
            shadow["reason"] = "native capture and renderer draw counts differ"
            shadow["parts"] = [
                self._shadow_part_defaults(
                    len(reconstruction_candidates),
                    final_pixel_verify_enabled=self.final_pixel_verify_enabled,
                )
                for _ in native_captures
            ]
            finish_timing()
            return LosslessReconstructionEvaluation(shadow, None)

        requested_mapping_ids: list[str] = []
        requested_mapping_ids_seen: set[str] = set()
        for draw_call in selected_draw_calls:
            mapping_id = draw_call.get("mappingId", draw_call.get("mapping_id"))
            if mapping_id is None:
                shadow["reason"] = "selected renderer draw mapping identity unavailable"
                shadow["parts"] = [
                    self._shadow_part_defaults(
                        len(reconstruction_candidates),
                        final_pixel_verify_enabled=self.final_pixel_verify_enabled,
                    )
                    for _ in native_captures
                ]
                finish_timing()
                return LosslessReconstructionEvaluation(shadow, None)
            normalized_mapping_id = str(mapping_id)
            if normalized_mapping_id not in requested_mapping_ids_seen:
                requested_mapping_ids_seen.add(normalized_mapping_id)
                requested_mapping_ids.append(normalized_mapping_id)
        shadow["trace_requested_mapping_count"] = len(requested_mapping_ids)
        trace_fetch_started = time.perf_counter()
        try:
            compact_payload = await page.evaluate(
                _SELECTED_COMPLETED_MAPPINGS_COMPACT_SCRIPT,
                requested_mapping_ids,
            )
        except Exception:  # noqa: BLE001 - missing trace means unavailable
            compact_payload = None
        evaluation_timing["selected_trace_fetch_ms"] = _elapsed_ms(trace_fetch_started)
        trace_decode_started = time.perf_counter()
        trace = decode_compact_completed_mappings(compact_payload)
        evaluation_timing["selected_trace_decode_ms"] = _elapsed_ms(
            trace_decode_started
        )
        if not isinstance(trace, dict):
            shadow["reason"] = "compact trace unavailable or invalid"
            shadow["parts"] = [
                self._shadow_part_defaults(
                    len(reconstruction_candidates),
                    final_pixel_verify_enabled=self.final_pixel_verify_enabled,
                )
                for _ in native_captures
            ]
            finish_timing()
            return LosslessReconstructionEvaluation(shadow, None)
        shadow.update(_trace_payload_stats(trace))
        shadow["retained_completed_mapping_summaries"] = trace.get(
            "retainedCompletedMappingSummaries", []
        )
        selected_clear_evidence: list[dict[str, Any]] = []
        requested_mapping_ids_set = set(requested_mapping_ids)
        for mapping in trace.get("completedMappings", []):
            if not isinstance(mapping, dict):
                continue
            mapping_id = mapping.get("mappingId")
            if str(mapping_id) not in requested_mapping_ids_set:
                continue
            selected_clear_evidence.append({
                "mappingId": mapping_id,
                "trace": "selected",
                "segmentClearOperationIndex": mapping.get(
                    "segmentClearOperationIndex"
                ),
                "segmentExecutedFullClearWitness": mapping.get(
                    "segmentExecutedFullClearWitness"
                ),
                "segmentExecutedFullClearWitnessRejection": mapping.get(
                    "segmentExecutedFullClearWitnessRejection"
                ),
            })
        shadow["selected_mapping_clear_evidence"] = selected_clear_evidence

        initial_analyses: list[MappingAnalysis] = []
        initial_analysis_times: list[float] = []
        provenance_candidates: list[Any | None] = []
        for draw_call in selected_draw_calls:
            mapping_started = time.perf_counter()
            initial_analysis = analyze_purchased_mapping(trace, draw_call)
            mapping_elapsed = _elapsed_ms(mapping_started)
            initial_analyses.append(initial_analysis)
            initial_analysis_times.append(mapping_elapsed)
            evaluation_timing["trace_python_analysis_ms"] += mapping_elapsed
            evaluation_timing["mapping_analysis"] += mapping_elapsed
            candidate = None
            if not initial_analysis.proven:
                candidate = resolve_scaled_canvas_source_candidate(
                    initial_analysis,
                    draw_call,
                    trace.get("retainedCompletedMappingSummaries", []),
                )
            provenance_candidates.append(candidate)

        upstream_mapping_ids: list[str] = []
        upstream_mapping_ids_seen: set[str] = set()
        for candidate in provenance_candidates:
            if candidate is None or candidate.upstream_mapping_id in upstream_mapping_ids_seen:
                continue
            upstream_mapping_ids_seen.add(candidate.upstream_mapping_id)
            upstream_mapping_ids.append(candidate.upstream_mapping_id)
        upstream_trace: dict[str, Any] | None = None
        if upstream_mapping_ids:
            upstream_fetch_started = time.perf_counter()
            try:
                upstream_payload = await page.evaluate(
                    _SELECTED_COMPLETED_MAPPINGS_COMPACT_SCRIPT,
                    upstream_mapping_ids,
                )
            except Exception:  # noqa: BLE001 - missing upstream trace is fallback
                upstream_payload = None
            evaluation_timing["upstream_trace_fetch_ms"] = _elapsed_ms(
                upstream_fetch_started
            )
            upstream_decode_started = time.perf_counter()
            upstream_trace = decode_compact_completed_mappings(upstream_payload)
            evaluation_timing["upstream_trace_decode_ms"] = _elapsed_ms(
                upstream_decode_started
            )
        if isinstance(upstream_trace, dict):
            upstream_mapping_ids_set = set(upstream_mapping_ids)
            for mapping in upstream_trace.get("completedMappings", []):
                if not isinstance(mapping, dict):
                    continue
                mapping_id = mapping.get("mappingId")
                if str(mapping_id) not in upstream_mapping_ids_set:
                    continue
                selected_clear_evidence.append({
                    "mappingId": mapping_id,
                    "trace": "upstream",
                    "segmentClearOperationIndex": mapping.get(
                        "segmentClearOperationIndex"
                    ),
                    "segmentExecutedFullClearWitness": mapping.get(
                        "segmentExecutedFullClearWitness"
                    ),
                    "segmentExecutedFullClearWitnessRejection": mapping.get(
                        "segmentExecutedFullClearWitnessRejection"
                    ),
                })
        shadow["selected_mapping_clear_evidence"] = selected_clear_evidence
        evaluation_timing["trace_fetch_ms"] = (
            evaluation_timing["selected_trace_fetch_ms"]
            + evaluation_timing["upstream_trace_fetch_ms"]
        )
        evaluation_timing["trace_decode_ms"] = (
            evaluation_timing["selected_trace_decode_ms"]
            + evaluation_timing["upstream_trace_decode_ms"]
        )

        analyses: list[MappingAnalysis] = []
        strict_executed_clear_flags: list[bool] = []
        strict_single_capture = _strict_executed_clear_capture_allowed(
            len(native_captures), len(selected_draw_calls)
        )
        analysis_times: list[float] = []
        for initial_analysis, candidate in zip(
            initial_analyses, provenance_candidates, strict=True
        ):
            if candidate is None:
                analyses.append(initial_analysis)
                strict_executed_clear_flags.append(False)
                analysis_times.append(0.0)
                continue
            upstream_analysis: MappingAnalysis
            upstream_elapsed = 0.0
            if upstream_trace is None:
                upstream_analysis = MappingAnalysis(
                    status="MAPPING_UNAVAILABLE",
                    reason="upstream compact mapping unavailable",
                    mapping_source="completed_segment",
                    mapping_id=candidate.upstream_mapping_id,
                    renderer_operation_index=candidate.copy_operation_index,
                    completed_mapping_evicted=True,
                )
            else:
                upstream_started = time.perf_counter()
                upstream_analysis = analyze_purchased_mapping(
                    upstream_trace,
                    candidate.upstream_renderer_draw(),
                )
                upstream_elapsed = _elapsed_ms(upstream_started)
                evaluation_timing["trace_python_analysis_ms"] += upstream_elapsed
                evaluation_timing["mapping_analysis"] += upstream_elapsed
            legacy_valid = validate_scaled_canvas_source_analysis(
                upstream_analysis,
                candidate,
            )
            strict_executed_clear_valid = False
            if not legacy_valid and strict_single_capture:
                strict_executed_clear_valid = validate_scaled_canvas_source_analysis(
                    upstream_analysis,
                    candidate,
                    allow_executed_full_clear=True,
                )
            if legacy_valid or strict_executed_clear_valid:
                assert upstream_analysis.mapping is not None
                scaled_mapping = replace(
                    upstream_analysis.mapping,
                    mapping_provenance="scaled_canvas_source_1hop",
                )
                upstream_analysis = replace(
                    upstream_analysis,
                    mapping=scaled_mapping,
                    mapping_provenance="scaled_canvas_source_1hop",
                )
            else:
                upstream_analysis = replace(
                    upstream_analysis,
                    reason=(
                        "scaled canvas upstream mapping failed provenance cross-check"
                    ),
                )
            analyses.append(upstream_analysis)
            strict_executed_clear_flags.append(strict_executed_clear_valid)
            analysis_times.append(upstream_elapsed)
        self._p4b_atomic_proof_active = (
            self._diagnostic_p4b_atomic_proof
            or (strict_single_capture and any(strict_executed_clear_flags))
        )

        parts: list[dict[str, Any]] = []
        reconstructed_captures: list[CaptureResult] = []
        for (
            native,
            draw_call,
            analysis,
            provenance_candidate,
            initial_analysis_time,
            upstream_analysis_time,
            strict_executed_clear_valid,
        ) in zip(
            native_captures,
            selected_draw_calls,
            analyses,
            provenance_candidates,
            initial_analysis_times,
            analysis_times,
            strict_executed_clear_flags,
            strict=True,
        ):
            part = self._shadow_part_defaults(
                len(reconstruction_candidates),
                final_pixel_verify_enabled=self.final_pixel_verify_enabled,
            )
            part_timing = _part_timing_defaults()
            part["timing_ms"] = part_timing
            part_timing["mapping_analysis_ms"] = round(
                initial_analysis_time + upstream_analysis_time,
                2,
            )
            part["selected_mapping_id"] = draw_call.get(
                "mappingId", draw_call.get("mapping_id")
            )
            part["executed_clear_provenance"] = strict_executed_clear_valid
            if provenance_candidate is not None:
                part.update(provenance_candidate.to_debug())
            analysis_debug = analysis.to_debug()
            for key in (
                "mapping_source",
                "mapping_id",
                "renderer_operation_index",
                "segment_clear_operation_index",
                "segment_first_tile_operation_index",
                "segment_last_tile_operation_index",
                "segment_tile_count",
                "segment_expected_tile_count",
                "segment_overflow",
                "completed_mapping_evicted",
                "renderer_geometry_classification",
                "mapping_provenance",
                "renderer_canvas_id",
                "source_canvas_id",
                "coded_dimensions",
                "visible_dimensions",
                "tile_dimensions_uniform",
                "tile_dimension_variants",
                "unsafe_operation_count",
                "first_unsafe_operation_index",
                "unsafe_operation_types",
                "non_image_bitmap_draws",
                "segment_reset_observation_available",
                "segment_mutation_observer_available",
                "segment_mutation_observer_take_records_available",
            ):
                if key in analysis_debug:
                    part[key] = analysis_debug[key]
            part["mapping_proven"] = analysis.proven
            part["mapping_status"] = analysis.status
            part["mapping_reason"] = analysis.reason
            part["trace_overflow"] = analysis.trace_overflow
            if analysis.proven and part.get("mapping_provenance") is None:
                part["mapping_provenance"] = "direct"
            if provenance_candidate is not None:
                part["scaled_canvas_source_provenance"] = bool(
                    analysis.proven
                    and analysis.mapping_provenance == "scaled_canvas_source_1hop"
                )
            if not analysis.proven or analysis.mapping is None:
                parts.append(part)
                continue
            mapping = analysis.mapping
            part["mapping_sha256"] = mapping.mapping_sha256
            part["tile_dimensions"] = list(mapping.tile_dimensions)
            part["mcu_dimensions"] = list(mapping.mcu_dimensions)
            coded_dimensions = mapping.coded_dimensions or mapping.source_dimensions
            visible_dimensions = mapping.visible_dimensions or mapping.destination_dimensions
            cropped_coded_frame = coded_dimensions != visible_dimensions
            part["coded_dimensions"] = list(coded_dimensions)
            part["visible_dimensions"] = list(visible_dimensions)
            part["tile_dimensions_uniform"] = mapping.tile_dimensions_uniform
            part["tile_dimension_variants"] = [list(item) for item in mapping.tile_dimension_variants]
            part["strict_mcu_aligned"] = all(
                value % 8 == 0
                for item in mapping.mapping
                for value in (
                    item["source_x"], item["source_y"], item["destination_x"],
                    item["destination_y"], item["width"], item["height"],
                )
            )
            source_id = mapping.imagebitmap_source_id
            if not source_id:
                part["reason"] = "ImageBitmap source identity unavailable"
                parts.append(part)
                continue
            dimension_candidates = tuple(
                candidate
                for candidate in reconstruction_candidates
                if (candidate.width, candidate.height) == mapping.source_dimensions
            )
            part["candidate_count_dimension_match"] = len(dimension_candidates)
            if not dimension_candidates:
                part["reason"] = "no reconstruction JPEG candidate has matching dimensions"
                parts.append(part)
                continue
            imagebitmap_signature_started = time.perf_counter()
            source_signature = await imagebitmap_signature(page, source_id)
            imagebitmap_elapsed = _elapsed_ms(imagebitmap_signature_started)
            part_timing["imagebitmap_signature_ms"] = imagebitmap_elapsed
            evaluation_timing["imagebitmap_signature"] += imagebitmap_elapsed
            part["imagebitmap_signature_available"] = source_signature is not None
            if source_signature is None:
                part["reason"] = "ImageBitmap signature unavailable"
                parts.append(part)
                continue
            signature_candidates: list[Any] = []
            candidate_signature_started = time.perf_counter()
            for candidate in dimension_candidates:
                if candidate.signature is None:
                    candidate.signature = await image_signature(
                        page,
                        candidate.data,
                        candidate.mime_type,
                    )
                if candidate.signature == source_signature:
                    signature_candidates.append(candidate)
            candidate_signature_elapsed = _elapsed_ms(candidate_signature_started)
            part_timing["candidate_signature_ms_total"] = candidate_signature_elapsed
            evaluation_timing["candidate_signature_total"] += candidate_signature_elapsed
            part["candidate_count_signature_match"] = len(signature_candidates)
            if not signature_candidates:
                part["reason"] = "no reconstruction JPEG candidate has matching signature"
                parts.append(part)
                continue
            matches: list[Any] = []
            raw_compare_started = time.perf_counter()
            for candidate in signature_candidates:
                comparison = await imagebitmap_pixel_exact_match(
                    page,
                    candidate.data,
                    source_id,
                )
                part["full_resolution_comparison_count"] += 1
                if comparison.get("available") and comparison.get("exact"):
                    matches.append(candidate)
            raw_compare_elapsed = _elapsed_ms(raw_compare_started)
            part_timing["raw_full_resolution_compare_ms"] = raw_compare_elapsed
            evaluation_timing["raw_full_resolution_compare"] += raw_compare_elapsed
            part["candidate_count_full_exact"] = len(matches)
            part["raw_jpeg_match_count"] = len(matches)
            if len(matches) != 1:
                part["reason"] = "raw JPEG match unavailable or ambiguous"
                parts.append(part)
                continue
            candidate = matches[0]
            part["raw_jpeg_exact"] = True
            reconstruction_started = time.perf_counter()
            result: LosslessJpegResult = await asyncio.to_thread(
                reconstruct_lossless_jpeg,
                candidate.data,
                mapping,
            )
            reconstruction_elapsed = _elapsed_ms(reconstruction_started)
            part_timing["lossless_reconstruction_ms"] = reconstruction_elapsed
            evaluation_timing["lossless_reconstruction"] += reconstruction_elapsed
            part["jpeg_supported"] = result.available
            part["coefficient_validation"] = result.coefficient_validation
            part["lossless_timing_ms"] = dict(result.timing)
            selectors_equal = (
                result.coefficient_validation.get(
                    "component_quantization_selectors_equal"
                ) is True
            )
            part["coefficient_exact"] = bool(
                result.available
                and result.coefficient_validation.get("mismatched_blocks") == 0
                and result.coefficient_validation.get("mismatched_coefficients") == 0
                and result.coefficient_validation.get("quantization_tables_equal") is True
                and (selectors_equal if cropped_coded_frame else True)
            )
            part["mismatched_blocks"] = result.coefficient_validation.get(
                "mismatched_blocks"
            )
            part["mismatched_coefficients"] = result.coefficient_validation.get(
                "mismatched_coefficients"
            )
            part["quantization_tables_equal"] = result.coefficient_validation.get(
                "quantization_tables_equal"
            )
            part["component_quantization_selectors_equal"] = result.coefficient_validation.get(
                "component_quantization_selectors_equal"
            )
            part["reconstruction_reason"] = result.reason
            if result.available and result.data is not None:
                part["reconstructed_byte_size"] = len(result.data)
                part["reconstructed_sha256"] = hashlib.sha256(result.data).hexdigest()
                part["reconstructed_dimensions_match"] = (
                    result.width == native.width and result.height == native.height
                )
                part["reconstructed_source_dimensions_match"] = (
                    result.width == coded_dimensions[0]
                    and result.height == coded_dimensions[1]
                )
                part["reconstructed_visible_dimensions_match"] = (
                    result.width == visible_dimensions[0]
                    and result.height == visible_dimensions[1]
                )
                part["final_pixel_comparison_mode"] = (
                    "scaled_source_to_native"
                    if part.get("mapping_provenance") == "scaled_canvas_source_1hop"
                    else "intrinsic"
                )
                mandatory_intrinsic_verify = coded_dimensions != visible_dimensions
                if self.final_pixel_verify_enabled or mandatory_intrinsic_verify:
                    final_compare_started = time.perf_counter()
                    if (
                        provenance_candidate is not None
                        and part.get("mapping_provenance")
                        == "scaled_canvas_source_1hop"
                        and cropped_coded_frame
                    ):
                        source_snapshot = await self._materialize_canvas_snapshot(
                            page, mapping.source_snapshot_id
                        )
                        part["source_snapshot_id"] = mapping.source_snapshot_id
                        part["source_snapshot_available"] = source_snapshot is not None
                        comparison = await self._browser_cropped_one_hop_pixel_exact(
                            page,
                            result.data,
                            draw_call,
                            provenance_candidate,
                            mapping,
                            source_snapshot,
                        )
                        if self._p4b_atomic_proof_active and len(selected_draw_calls) == 1:
                            comparison["p4b_atomic_current_roi"] = (
                                await self._p4b_current_roi_atomic_proof(
                                    page,
                                    draw_call,
                                    p4b_initial_anchor,
                                        p4b_renderer_handle,
                                        part.get("provenance_renderer_trace_epoch"),
                                )
                            )
                        part["cropped_chain_pixel_comparison"] = comparison
                        stage_comparisons = (
                            comparison.get("source"),
                            comparison.get("intermediate"),
                            comparison.get("final"),
                        )
                        part["cropped_chain_pixel_exact"] = bool(
                            comparison.get("available") is True
                            and comparison.get("dimensions_equal") is True
                            and comparison.get("exact") is True
                            and all(
                                isinstance(stage, dict)
                                and stage.get("available") is True
                                and stage.get("dimensions_equal") is True
                                and stage.get("exact") is True
                                for stage in stage_comparisons
                            )
                        )
                        if self._p4b_atomic_proof_active:
                            p4b_atomic = comparison.get("p4b_atomic_current_roi")
                            if not isinstance(p4b_atomic, dict) or p4b_atomic.get("exact") is not True:
                                part["cropped_chain_pixel_exact"] = False
                                part["reason"] = (
                                    "P4B current DOM ROI or final atomic anchor unavailable"
                                )
                    elif (
                        provenance_candidate is not None
                        and part.get("mapping_provenance")
                        == "scaled_canvas_source_1hop"
                    ):
                        comparison = await self._browser_scaled_source_pixel_exact(
                            page,
                            result.data,
                            native.data,
                            source_rect=provenance_candidate.source_rect,
                            destination=provenance_candidate.destination,
                            target_dimensions=provenance_candidate.target_dimensions,
                            image_smoothing_enabled=(
                                provenance_candidate.image_smoothing_enabled
                            ),
                            image_smoothing_quality=(
                                provenance_candidate.image_smoothing_quality
                            ),
                        )
                    else:
                        comparison = await self._browser_pixel_exact(
                            page, result.data, native.data
                        )
                    final_compare_elapsed = _elapsed_ms(final_compare_started)
                    part_timing["final_browser_pixel_compare_ms"] = final_compare_elapsed
                    evaluation_timing["final_browser_pixel_compare"] += final_compare_elapsed
                    part["final_pixel_compare_performed"] = True
                    comparison_dimensions_equal = comparison.get("dimensions_equal") is True
                    part["native_pixel_exact"] = bool(
                        comparison.get("available")
                        and comparison_dimensions_equal
                        and comparison.get("exact")
                    )
                    part["native_pixel_dimensions_equal"] = comparison_dimensions_equal
                    part["native_pixel_comparison"] = {
                        key: value
                        for key, value in comparison.items()
                        if key in {
                            "available", "exact", "dimensions_equal",
                            "differing_pixel_count", "max_channel_difference", "reason",
                        }
                    }
                if (
                    (
                        cropped_coded_frame
                        and part["reconstructed_visible_dimensions_match"]
                        and (
                            part.get("mapping_provenance") != "scaled_canvas_source_1hop"
                            or part.get("cropped_chain_pixel_exact") is True
                        )
                    )
                    or (
                        not cropped_coded_frame
                        and (
                            part["reconstructed_source_dimensions_match"]
                            or part.get("mapping_provenance")
                            == "scaled_canvas_source_1hop"
                        )
                    )
                ):
                    reconstructed_captures.append(
                        CaptureResult(
                            data=result.data,
                            width=result.width,
                            height=result.height,
                            mime_type="image/jpeg",
                            file_extension=".jpg",
                        )
                    )
            parts.append(part)
        shadow["parts"] = parts
        shadow["final_pixel_compare_performed"] = any(
            part.get("final_pixel_compare_performed") is True for part in parts
        )
        shadow["spread_ready"] = bool(parts) and all(
            part.get("mapping_proven") is True
            and part.get("mapping_source") == "completed_segment"
            and part.get("segment_overflow") is False
            and part.get("completed_mapping_evicted") is False
            and part.get("raw_jpeg_exact") is True
            and part.get("candidate_count_full_exact") == 1
            and part.get("jpeg_supported") is True
            and part.get("strict_mcu_aligned") is True
            and part.get("coefficient_exact") is True
            and part.get("quantization_tables_equal") is True
            and (
                part.get("component_quantization_selectors_equal") is True
                if part.get("coded_dimensions") != part.get("visible_dimensions")
                else True
            )
            and (
                part.get("reconstructed_source_dimensions_match") is True
                if part.get("coded_dimensions") == part.get("visible_dimensions")
                else part.get("reconstructed_visible_dimensions_match") is True
            )
            and (
                part.get("mapping_provenance") == "direct"
                and part.get("reconstructed_dimensions_match") is True
                or (
                    part.get("mapping_provenance")
                    == "scaled_canvas_source_1hop"
                    and part.get("scaled_canvas_source_provenance") is True
                )
            )
            and (
                (
                    part.get("coded_dimensions") != part.get("visible_dimensions")
                    and (
                        part.get("cropped_chain_pixel_exact") is True
                        if part.get("mapping_provenance") == "scaled_canvas_source_1hop"
                        else part.get("native_pixel_exact") is True
                    )
                )
                or (
                    part.get("coded_dimensions") == part.get("visible_dimensions")
                    and (
                        not self.final_pixel_verify_enabled
                        or part.get("native_pixel_exact") is True
                    )
                )
            )
            for part in parts
        )
        if not shadow["spread_ready"]:
            shadow["reason"] = "one or more parts are not reconstruction-ready"
        captures = (
            tuple(reconstructed_captures)
            if shadow["spread_ready"]
            and len(reconstructed_captures) == len(native_captures)
            else None
        )
        if captures is None:
            shadow["spread_ready"] = False
            if "reason" not in shadow:
                shadow["reason"] = "verified reconstructed captures are incomplete"
        finish_timing()
        return LosslessReconstructionEvaluation(shadow, captures)

    async def _maybe_reselect_lossless_reconstruction(
        self,
        page: Page,
        first: LosslessReconstructionEvaluation,
        native_captures: tuple[CaptureResult, ...],
        selected_draw_calls: list[dict[str, Any]],
        *,
        p4b_initial_anchor: dict[str, Any] | None,
        p4b_renderer_handle: Any | None,
    ) -> LosslessReconstructionEvaluation:
        """Retry one strict clear proof after a same-source renderer redraw.

        This is deliberately limited to the newly validated executed-clear
        path. Legacy dimension-reset and ordinary PNG paths never enter here.
        A failed identity/anchor check remains fail-closed; the caller must
        not return the old native pixels under a changed DOM target.
        """

        if (
            self._diagnostic_p4b_atomic_proof
            or not self._p4b_atomic_proof_active
            or self._p4b_redraw_attempted
        ):
            return first
        parts = [
            part
            for part in first.debug.get("parts", [])
            if isinstance(part, dict)
        ]
        atomic_failures = []
        for part in parts:
            comparison = part.get("cropped_chain_pixel_comparison")
            proof = comparison.get("p4b_atomic_current_roi") if isinstance(comparison, dict) else None
            if isinstance(proof, dict) and proof.get("exact") is not True:
                atomic_failures.append(proof)
        if not atomic_failures:
            return first
        failure = atomic_failures[0]
        if failure.get("reason") != "initial renderer anchor changed":
            if failure.get("reason") in {
                "current capture target identity changed",
                "current renderer canvas is missing or ambiguous",
                "original renderer element is unavailable",
                "final renderer anchor changed",
                "selected renderer B anchor mismatch",
            }:
                raise UnknownPageStateError(
                    "BookWalker strict clear proof anchor changed outside a retryable race"
                )
            # A stable proof failure (for example an unavailable immutable
            # snapshot) may safely keep the normal PNG fallback. Only an
            # identity transition must bypass the optional-capture fallback.
            return first
        if len(parts) != 1 or not _initial_proof_ready_for_redraw(parts[0]):
            raise UnknownPageStateError(
                "BookWalker strict clear proof lacks complete initial immutable proof"
            )
        initial = p4b_initial_anchor
        before = failure.get("before")
        old_call = selected_draw_calls[0] if len(selected_draw_calls) == 1 else None
        if not isinstance(initial, dict) or not isinstance(before, dict) or not isinstance(old_call, dict):
            raise UnknownPageStateError(
                "BookWalker strict clear proof lacks initial anchor or selected draw"
            )
        anchor_fields = (
            "traceId", "actualCanvasId", "bookIdentity", "counter",
            "geometryToken", "traceEpoch",
        )
        for anchor in (initial, before):
            if any(anchor.get(field) in (None, "") for field in anchor_fields):
                raise UnknownPageStateError(
                    "BookWalker strict clear proof anchor identity is incomplete"
                )
            if (
                anchor.get("connected") is not True
                or anchor.get("geometryHistoryIncomplete") is not False
                or anchor.get("unknownMutation") is not False
                or self._initial_content_id is None
                or anchor.get("bookIdentity") != self._initial_content_id
            ):
                raise UnknownPageStateError(
                    "BookWalker strict clear proof initial anchor is not stable"
                )
        if any(initial.get(field) != before.get(field) for field in anchor_fields):
            raise UnknownPageStateError(
                "BookWalker strict clear proof changed before retry"
            )
        initial_selected = initial.get("selected")
        old_operation = old_call.get("traceOperationIndex")
        selected_fields = (
            "canvasId", "operationIndex", "sourceId", "sourceCanvasId",
            "traceEpoch", "sourceRect", "destination",
        )
        if (
            not isinstance(initial_selected, dict)
            or any(initial_selected.get(field) in (None, "") for field in selected_fields)
            or old_operation != initial_selected.get("operationIndex")
            or not isinstance(old_operation, int)
            or isinstance(old_operation, bool)
        ):
            raise UnknownPageStateError(
                "BookWalker strict clear proof selected draw identity is incomplete"
            )
        self._p4b_redraw_attempted = True
        redraw: dict[str, Any] = {
            "attempted": True,
            "initial_operation": old_operation,
            "reason": failure.get("reason"),
            "selected": False,
        }
        try:
            canvas = await self.get_capture_target(page)
            current_handle = await canvas.element_handle()
            if current_handle is None or p4b_renderer_handle is None:
                raise CaptureUnavailableError("renderer element handle unavailable")
            same_renderer = await page.evaluate(
                "([original, current]) => original === current",
                [p4b_renderer_handle, current_handle],
            )
            if same_renderer is not True:
                raise CaptureUnavailableError("renderer element identity changed before redraw")
            size = await canvas.evaluate(
                "element => ({width: element.width, height: element.height})"
            )
            trace_id = await canvas.get_attribute("data-bookwalker-trace-id")
            boxes = await self._page_draw_rectangles(page, canvas)
            calls = await page.evaluate(
                "traceId => (window.__bookwalkerNativeDrawCalls || []).filter(call => call.canvasId === traceId)",
                trace_id,
            )
            selection_debug: dict[str, Any] = {"box_count": len(boxes)}
            current = select_native_draw_calls(
                calls if isinstance(calls, list) else [],
                canvas_id=trace_id,
                canvas_width=int(size["width"]),
                canvas_height=int(size["height"]),
                boxes=boxes,
                selection_debug=selection_debug,
            )
            redraw["selector"] = selection_debug
            if not current or len(current) != len(boxes) or len(current) != 1:
                raise CaptureUnavailableError("current draw was not uniquely selected")
            new_call = current[0]
            new_operation = new_call.get("traceOperationIndex")
            redraw["new_operation"] = new_operation
            if (
                not isinstance(new_operation, int)
                or isinstance(new_operation, bool)
                or new_operation <= old_operation
            ):
                raise CaptureUnavailableError("no newer current redraw operation")
            for key in ("sourceId", "sourceCanvasId", "sourceRect", "destination"):
                if new_call.get(key) != old_call.get(key):
                    raise CaptureUnavailableError(f"redraw {key} changed")
            if new_call.get("traceEpoch") != old_call.get("traceEpoch"):
                raise CaptureUnavailableError("redraw trace epoch changed")
            if not _native_call_is_safe(new_call):
                raise CaptureUnavailableError("redraw native safety gate failed")
            materialized = await self._materialize_native_source_crops(page, current)
            if len(materialized) != 1:
                raise CaptureUnavailableError("redraw materialization was not unique")
            source_rect = new_call.get("sourceRect")
            source = new_call.get("source")
            if not isinstance(source_rect, dict) or not isinstance(source, dict):
                raise CaptureUnavailableError("redraw source geometry unavailable")
            expected_width = round(float(source_rect["width"]))
            expected_height = round(float(source_rect["height"]))
            source_width = float(source["width"])
            source_height = float(source["height"])
            if (
                source_rect.get("x") != 0
                or source_rect.get("y") != 0
                or expected_width <= 0
                or expected_height <= 0
                or expected_width > source_width
                or expected_height > source_height
            ):
                raise CaptureUnavailableError("redraw source bounds are invalid")
            current_capture = _capture_from_data_url(materialized[0].get("sourceCropPng"))
            if (current_capture.width, current_capture.height) != (expected_width, expected_height):
                raise CaptureUnavailableError("redraw native PNG dimensions do not match")
            new_anchor = await current_handle.evaluate(
                _BOOKWALKER_NATIVE_ANCHOR_SCRIPT,
                new_operation,
            )
            new_selected = new_anchor.get("selected") if isinstance(new_anchor, dict) else None
            if not isinstance(new_selected, dict):
                raise CaptureUnavailableError("redraw anchor is incomplete")
            if any(new_anchor.get(field) != initial.get(field) for field in anchor_fields):
                raise CaptureUnavailableError("redraw page or canvas identity changed")
            for field in selected_fields:
                if new_selected.get(field) != (new_operation if field == "operationIndex" else initial_selected.get(field)):
                    raise CaptureUnavailableError("redraw selected anchor changed")
            redraw["selected"] = True
            rerun = await self._evaluate_lossless_reconstruction(
                page,
                (current_capture,),
                materialized,
                p4b_initial_anchor=new_anchor,
                p4b_renderer_handle=current_handle,
            )
            rerun_parts = [
                part for part in rerun.debug.get("parts", [])
                if isinstance(part, dict)
                and part.get("executed_clear_provenance") is True
            ]
            if len(rerun_parts) != 1:
                raise UnknownPageStateError(
                    "BookWalker strict redraw proof is missing its fresh part"
                )
            rerun_proof = (
                rerun_parts[0].get("cropped_chain_pixel_comparison") or {}
            ).get("p4b_atomic_current_roi")
            if not isinstance(rerun_proof, dict):
                raise UnknownPageStateError(
                    "BookWalker strict redraw proof is missing its fresh anchor"
                )
            if rerun_proof.get("reason") in {
                "current capture target identity changed",
                "current renderer canvas is missing or ambiguous",
                "original renderer element is unavailable",
                "initial renderer anchor changed",
                "final renderer anchor changed",
                "selected renderer B anchor mismatch",
            }:
                raise UnknownPageStateError(
                    "BookWalker strict redraw proof changed identity again"
                )
            self._p4b_redraw_native_captures = (current_capture,)
            self._p4b_redraw_selected_draw_calls = current
            rerun.debug["p4b_redraw_reselection"] = redraw
            return rerun
        except (CaptureUnavailableError, PlaywrightError, PlaywrightTimeoutError, TimeoutError, KeyError, TypeError, ValueError) as exc:
            redraw["reason"] = f"redraw reselection failed: {type(exc).__name__}"
        first.debug["p4b_redraw_reselection"] = redraw
        self._capture_debug["bookwalker_capture"]["lossless_shadow"] = first.debug
        self._capture_debug["bookwalker_capture"]["strict_abort_reason"] = redraw["reason"]
        raise UnknownPageStateError(
            "BookWalker strict clear proof could not complete a fresh same-source redraw"
        )

    async def collect_debug_metadata(self, page: Page) -> dict[str, Any]:
        del page
        return copy.deepcopy(self._capture_debug)

    async def _clear_native_capture(self, page: Page) -> None:
        try:
            await page.evaluate(
                """
                () => {
                  window.__bookwalkerNativeCaptureEnabled = false;
                  window.__bookwalkerNativeDrawCalls = [];
                  window.__bookwalkerNativeSourceObjects?.clear();
                  window.__bookwalkerNativeSnapshots?.clear();
                }
                """
            )
        except (PlaywrightError, PlaywrightTimeoutError, TimeoutError):
            return

    async def _clear_geometry_trace(self, page: Page) -> None:
        try:
            await page.evaluate(
                """
                () => {
                  window.__bookwalkerDrawCalls = [];
                  window.__bookwalkerResetDirectOneHop?.();
                  window.__bookwalkerResetTransformTrace?.();
                }
                """
            )
        except (PlaywrightError, PlaywrightTimeoutError, TimeoutError):
            return

    async def _arm_native_capture(self, page: Page) -> None:
        if self.capture_mode != "native":
            return
        try:
            await page.evaluate(
                """
                () => {
                  window.__bookwalkerNativeDrawCalls = [];
                  window.__bookwalkerResetNativeCaptureDiagnostics?.();
                  window.__bookwalkerResetDirectOneHop?.();
                  window.__bookwalkerNativeSourceObjects?.clear();
                  window.__bookwalkerNativeSnapshots?.clear();
                  window.__bookwalkerResetTransformTrace?.();
                  window.__bookwalkerNativeCaptureEnabled = true;
                  // The direct one-hop ledger is a cover-only path.  Initial
                  // page capture uses the prepare-page flag; navigation arms
                  // native tracing for body pages without retaining full-frame
                  // direct snapshots.
                  window.__bookwalkerDirectOriginalEnabled = false;
                }
                """
            )
        except (PlaywrightError, PlaywrightTimeoutError, TimeoutError):
            return

    async def _materialize_native_source_crops(
        self,
        page: Page,
        selected: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        payload = [
            {
                "sourceId": call.get("sourceId"),
                "snapshotId": call.get("snapshotId"),
                "fullSourceSnapshotId": call.get("fullSourceSnapshotId"),
                "targetSnapshotId": call.get("targetSnapshotId"),
                "sourceConstructor": (
                    call.get("source", {}).get("constructor")
                    if isinstance(call.get("source"), dict)
                    else None
                ),
                "sourceRect": call.get("sourceRect"),
            }
            for call in selected
        ]
        results = await page.evaluate(
            _MATERIALIZE_NATIVE_SOURCE_SCRIPT,
            payload,
        )
        if not isinstance(results, list) or len(results) != len(selected):
            raise CaptureUnavailableError(
                "BookWalker native source crop materialization failed"
            )
        materialized: list[dict[str, Any]] = []
        for call, result in zip(selected, results, strict=True):
            if not isinstance(result, dict):
                raise CaptureUnavailableError(
                    "BookWalker native source crop result is invalid"
                )
            enriched = dict(call)
            enriched["sourceCropPng"] = result.get("dataUrl")
            enriched["sourceCropPngError"] = result.get("error")
            enriched["fullSourcePng"] = result.get("fullSourceDataUrl")
            enriched["fullSourcePngError"] = result.get("fullSourceError")
            enriched["targetCropPng"] = result.get("targetDataUrl")
            enriched["targetCropPngError"] = result.get("targetError")
            materialized.append(enriched)
        return materialized

    async def capture_page(self, page: Page) -> tuple[CaptureResult, ...] | None:
        """Prefer native source crops and return None for the legacy fallback."""

        if self.capture_mode == "canvas":
            self._reset_capture_debug()
            self._capture_debug["bookwalker_capture"]["returned_path"] = "rendered_canvas"
            return None
        self._reset_capture_debug()
        capture_started = time.perf_counter()
        selected_draw_calls: list[dict[str, Any]] = []
        self._p4b_atomic_proof_active = self._diagnostic_p4b_atomic_proof
        self._p4b_redraw_attempted = False
        self._p4b_redraw_native_captures = None
        self._p4b_redraw_selected_draw_calls = None
        try:
            canvas = await self.get_capture_target(page)
            p4b_renderer_handle: Any | None = None
            try:
                # Locator.element_handle() is the supported Playwright API.
                # Keep the real capture path independent of test-double shape.
                p4b_renderer_handle = await canvas.element_handle()
            except (PlaywrightError, PlaywrightTimeoutError, TimeoutError):
                p4b_renderer_handle = None
            if self._diagnostic_p4b_atomic_proof and p4b_renderer_handle is None:
                raise CaptureUnavailableError(
                    "BookWalker P4B renderer element handle is unavailable"
                )
            capture_canvas = p4b_renderer_handle or canvas
            trace_id = await capture_canvas.get_attribute("data-bookwalker-trace-id")
            if not trace_id:
                raise CaptureUnavailableError("BookWalker canvas trace id is missing")
            size = await capture_canvas.evaluate(
                "element => ({width: element.width, height: element.height})"
            )
            width = int(size["width"])
            height = int(size["height"])
            selection_geometry_state = await capture_canvas.evaluate(
                "element => window.__bookwalkerDirectOneHopGeometryState?.(element) || null",
            )
            boxes = await self._page_draw_rectangles(page, capture_canvas)
            selection_debug: dict[str, Any] = {
                "outcome": "rejected",
                "rejection_branch": None,
                "box_count": len(boxes),
            }
            self._capture_debug["bookwalker_capture"][
                "native_selection"
            ] = selection_debug
            first_page = await self._is_first_page(page)
            if not boxes:
                selection_debug["rejection_branch"] = "no_page_boxes"
                raise CaptureUnavailableError(
                    "BookWalker native capture requires draw geometry"
                )
            if len(boxes) > 1 and first_page:
                selection_debug["rejection_branch"] = "cover_spread_requires_union"
                raise CaptureUnavailableError(
                    "BookWalker cover spread needs one fallback union crop"
                )
            draw_calls = await page.evaluate(
                """
                traceId => (window.__bookwalkerNativeDrawCalls || [])
                  .filter(call => call.canvasId === traceId)
                """,
                trace_id,
            )
            if not isinstance(draw_calls, list):
                draw_calls = []
            selected = select_native_draw_calls(
                draw_calls,
                canvas_id=trace_id,
                canvas_width=width,
                canvas_height=height,
                boxes=boxes,
                selection_debug=selection_debug,
            )
            try:
                runtime_selection = await page.evaluate(
                    "() => window.__bookwalkerNativeCaptureDiagnostics || null"
                )
            except (PlaywrightError, PlaywrightTimeoutError, TimeoutError):
                runtime_selection = None
            if isinstance(runtime_selection, dict):
                selection_debug["runtime"] = self._safe_diagnostic_value(
                    runtime_selection
                )
            if selected is None or len(selected) != len(boxes):
                selection_debug.setdefault(
                    "rejection_branch", "selector_rejected"
                )
                raise CaptureUnavailableError(
                    "BookWalker native source calls did not match page geometry"
                )
            selection_debug["outcome"] = "selected"
            selection_debug["selected_count"] = len(selected)
            selected_draw_calls = selected
            p4b_initial_anchor: dict[str, Any] | None = None
            if p4b_renderer_handle is not None and len(selected) == 1:
                selected_operation_index = selected[0].get("traceOperationIndex")
                if isinstance(selected_operation_index, int):
                    try:
                        p4b_initial_anchor = await capture_canvas.evaluate(
                            _BOOKWALKER_NATIVE_ANCHOR_SCRIPT,
                            selected_operation_index,
                        )
                    except (PlaywrightError, PlaywrightTimeoutError, TimeoutError):
                        p4b_initial_anchor = None
            materialization_started = time.perf_counter()
            selected = await self._materialize_native_source_crops(page, selected)
            selected_draw_calls = selected
            self._capture_debug["bookwalker_capture"]["selected_draw"] = [
                {
                    "traceOperationIndex": call.get("traceOperationIndex"),
                    "canvasId": call.get("canvasId"),
                    "sourceId": call.get("sourceId"),
                    "sourceCanvasId": call.get("sourceCanvasId"),
                    "sourceConstructor": (call.get("source") or {}).get("constructor"),
                    "source": call.get("source"),
                    "sourceRect": call.get("sourceRect"),
                    "destination": call.get("destination"),
                    "target": call.get("target"),
                    "mappingId": call.get("mappingId"),
                }
                for call in selected
            ]
            self._capture_debug["bookwalker_capture"]["timing_ms"][
                "native_materialization_ms"
            ] = _elapsed_ms(materialization_started)

            captures: list[CaptureResult] = []
            for call in selected:
                if not _native_call_is_safe(call):
                    raise CaptureUnavailableError(
                        "BookWalker native source uses unsupported composition"
                    )
                source_rect = call.get("sourceRect")
                if not isinstance(source_rect, dict):
                    raise CaptureUnavailableError(
                        "BookWalker native source rectangle is missing"
                    )
                try:
                    source = call["source"]
                    source_width = float(source["width"])
                    source_height = float(source["height"])
                    source_x = float(source_rect["x"])
                    source_y = float(source_rect["y"])
                    expected_width = round(float(source_rect["width"]))
                    expected_height = round(float(source_rect["height"]))
                except (KeyError, TypeError, ValueError) as exc:
                    raise CaptureUnavailableError(
                        "BookWalker native source rectangle is invalid"
                    ) from exc
                if (
                    source_width <= 0
                    or source_height <= 0
                    or source_x < 0
                    or source_y < 0
                    or expected_width <= 0
                    or expected_height <= 0
                    or source_x + expected_width > source_width
                    or source_y + expected_height > source_height
                ):
                    raise CaptureUnavailableError(
                        "BookWalker native source rectangle is out of bounds"
                    )
                capture = _capture_from_data_url(call.get("sourceCropPng"))
                if (capture.width, capture.height) != (expected_width, expected_height):
                    raise CaptureUnavailableError(
                        "BookWalker native PNG dimensions do not match source rectangle"
                    )
                captures.append(capture)
            if self.capture_mode != "native" or not self.enable_original_jpeg_capture:
                await self._clear_geometry_trace(page)
                return tuple(captures)
            native_captures = tuple(captures)
            original_match_started = time.perf_counter()
            original_captures = await self._capture_original_jpegs(
                page, native_captures
            )
            self._capture_debug["bookwalker_capture"]["timing_ms"][
                "original_jpeg_match_ms"
            ] = _elapsed_ms(original_match_started)
            if original_captures is not None:
                self._capture_debug["bookwalker_capture"]["returned_path"] = "original_jpeg"
                self._capture_debug["bookwalker_capture"]["lossless_shadow"] = {
                    "attempted": False,
                    "spread_ready": False,
                    "output_enabled": self.lossless_jpeg_output_enabled,
                    "output_used": False,
                    "final_pixel_verify_enabled": self.final_pixel_verify_enabled,
                    "final_pixel_compare_performed": False,
                    "parts": [],
                    "reason": "existing original JPEG exact match",
                }
                await self._clear_geometry_trace(page)
                return original_captures
            direct_started = time.perf_counter()
            direct_captures = None
            if first_page:
                direct_captures = await self._capture_direct_one_hop_original_jpeg(
                    page,
                    canvas,
                    selected_draw_calls[0],
                    selection_geometry_state,
                    p4b_renderer_handle,
                )
            else:
                self._capture_debug["bookwalker_capture"]["direct_original_jpeg"] = {
                    "attempted": False,
                    "accepted": False,
                    "reason": "direct one-hop path is cover-only",
                    "candidate_count": 0,
                    "exact_candidate_count": 0,
                    "records": [],
                }
            self._capture_debug["bookwalker_capture"]["timing_ms"][
                "direct_original_jpeg_ms"
            ] = _elapsed_ms(direct_started)
            if direct_captures is not None:
                self._capture_debug["bookwalker_capture"]["returned_path"] = (
                    "direct_original_jpeg"
                )
                self._capture_debug["bookwalker_capture"]["lossless_shadow"] = {
                    "attempted": False,
                    "spread_ready": False,
                    "output_enabled": self.lossless_jpeg_output_enabled,
                    "output_used": False,
                    "final_pixel_verify_enabled": self.final_pixel_verify_enabled,
                    "final_pixel_compare_performed": False,
                    "parts": [],
                    "reason": "direct one-hop original JPEG exact match",
                }
                await self._clear_geometry_trace(page)
                return direct_captures
            reconstruction_candidates = tuple(
                candidate
                for candidate in self._original_candidates.values()
                if is_reconstruction_jpeg_candidate(candidate)
            )
            if reconstruction_candidates:
                strict_proof_required = False
                try:
                    if self._diagnostic_p4b_atomic_proof or p4b_renderer_handle is not None:
                        evaluation = await self._evaluate_lossless_reconstruction(
                            page,
                            native_captures,
                            selected_draw_calls,
                            p4b_initial_anchor=p4b_initial_anchor,
                            p4b_renderer_handle=p4b_renderer_handle,
                        )
                    else:
                        evaluation = await self._evaluate_lossless_reconstruction(
                            page,
                            native_captures,
                            selected_draw_calls,
                        )
                    # Preserve the obligation for this capture attempt.  A
                    # bounded same-page redraw evaluates a fresh lineage and
                    # may update the mutable per-attempt flag; that must not
                    # make a failed second proof look like an ordinary PNG
                    # fallback.
                    strict_proof_required = self._p4b_atomic_proof_active
                    if strict_proof_required and not self._diagnostic_p4b_atomic_proof:
                        evaluation = await self._maybe_reselect_lossless_reconstruction(
                            page,
                            evaluation,
                            native_captures,
                            selected_draw_calls,
                            p4b_initial_anchor=p4b_initial_anchor,
                            p4b_renderer_handle=p4b_renderer_handle,
                        )
                        if self._p4b_redraw_native_captures is not None:
                            # The redraw is a new proof attempt.  Never let a
                            # later stable failure return the pre-redraw
                            # native buffer under the new selected lineage.
                            native_captures = self._p4b_redraw_native_captures
                            selected_draw_calls = (
                                self._p4b_redraw_selected_draw_calls
                                or selected_draw_calls
                            )
                            self._capture_debug["bookwalker_capture"][
                                "selected_draw"
                            ] = [
                                {
                                    "traceOperationIndex": call.get(
                                        "traceOperationIndex"
                                    ),
                                    "canvasId": call.get("canvasId"),
                                    "sourceId": call.get("sourceId"),
                                    "sourceCanvasId": call.get("sourceCanvasId"),
                                    "sourceConstructor": (
                                        (call.get("source") or {}).get(
                                            "constructor"
                                        )
                                    ),
                                    "source": call.get("source"),
                                    "sourceRect": call.get("sourceRect"),
                                    "destination": call.get("destination"),
                                    "target": call.get("target"),
                                    "mappingId": call.get("mappingId"),
                                }
                                for call in selected_draw_calls
                            ]
                except UnknownPageStateError:
                    raise
                except Exception as exc:
                    if strict_proof_required or self._p4b_atomic_proof_active:
                        raise UnknownPageStateError(
                            "BookWalker strict clear proof evaluation failed"
                        ) from exc
                    evaluation = LosslessReconstructionEvaluation(
                        debug={
                            "attempted": True,
                            "spread_ready": False,
                            "output_enabled": self.lossless_jpeg_output_enabled,
                            "output_used": False,
                            "final_pixel_verify_enabled": self.final_pixel_verify_enabled,
                            "final_pixel_compare_performed": False,
                            "parts": [],
                            "reason": f"lossless evaluation failed: {type(exc).__name__}",
                        },
                        captures=None,
                    )
                if strict_proof_required or self._p4b_atomic_proof_active:
                    strict_parts = [
                        part
                        for part in evaluation.debug.get("parts", [])
                        if isinstance(part, dict)
                        and part.get("executed_clear_provenance") is True
                    ]
                    if len(native_captures) == 1 and not strict_parts:
                        raise UnknownPageStateError(
                            "BookWalker strict clear proof part is missing"
                        )
                    strict_anchor_failures = [
                        (part.get("cropped_chain_pixel_comparison") or {})
                        .get("p4b_atomic_current_roi")
                        for part in strict_parts
                    ]
                    if len(native_captures) == 1 and any(
                        proof is None for proof in strict_anchor_failures
                    ):
                        raise UnknownPageStateError(
                            "BookWalker strict clear proof anchor is missing"
                        )
                    if len(native_captures) == 1 and any(
                        isinstance(proof, dict)
                        and not _p4b_stable_current_fallback_authority(proof)
                        for proof in strict_anchor_failures
                    ):
                        raise UnknownPageStateError(
                            "BookWalker strict clear proof lacks stable current anchor"
                        )
                    if any(
                        isinstance(proof, dict)
                        and proof.get("reason") in {
                            "current capture target identity changed",
                            "current renderer canvas is missing or ambiguous",
                            "original renderer element is unavailable",
                            "initial renderer anchor changed",
                            "final renderer anchor changed",
                            "selected renderer B anchor mismatch",
                        }
                        for proof in strict_anchor_failures
                    ):
                        # A strict executed-clear proof has already consumed the
                        # old renderer identity.  Letting this become the normal
                        # optional-capture exception would make Core fall back to
                        # a stale native PNG under the new DOM state.  Abort the
                        # page instead; ordinary legacy/PNG paths retain their
                        # existing optional fallback behavior.
                        raise UnknownPageStateError(
                            "BookWalker strict clear proof target identity changed"
                        )
                self._capture_debug["bookwalker_capture"]["lossless_shadow"] = (
                    evaluation.debug
                )
                self._capture_debug["bookwalker_capture"]["timing_ms"][
                    "lossless_evaluation_total_ms"
                ] = float(evaluation.debug.get("lossless_evaluation_total_ms", 0.0))
                if (
                    self.lossless_jpeg_output_enabled
                    and evaluation.debug.get("spread_ready") is True
                    and evaluation.captures is not None
                    and bool(evaluation.captures)
                    and len(evaluation.captures) == len(native_captures)
                ):
                    evaluation.debug["output_used"] = True
                    self._capture_debug["bookwalker_capture"]["returned_path"] = (
                        "reconstructed_jpeg"
                    )
                    await self._clear_geometry_trace(page)
                    return evaluation.captures
            else:
                self._capture_debug["bookwalker_capture"]["lossless_shadow"][
                    "reason"
                ] = "no JPEG candidates from supported reconstruction hosts"
            await self._clear_geometry_trace(page)
            self._capture_debug["bookwalker_capture"]["returned_path"] = "native_png"
            return native_captures
        except CaptureUnavailableError as exc:
            self._capture_debug["bookwalker_capture"]["failure_reason"] = str(exc)
            return None
        except UnknownPageStateError:
            raise
        except (
            BinasciiError,
            KeyError,
            LookupError,
            PlaywrightError,
            PlaywrightTimeoutError,
            TimeoutError,
            TypeError,
            ValueError,
        ) as exc:
            self._capture_debug["bookwalker_capture"]["failure_reason"] = (
                f"{type(exc).__name__}: {str(exc).splitlines()[0] if str(exc) else ''}"
            )
            return None
        finally:
            await self._clear_native_capture(page)
            capture_timing = self._capture_debug["bookwalker_capture"]["timing_ms"]
            capture_timing["capture_total_ms"] = _elapsed_ms(capture_started)
            capture_timing["capture_unaccounted_ms"] = round(
                capture_timing["capture_total_ms"]
                - capture_timing.get("native_materialization_ms", 0.0)
                - capture_timing.get("original_jpeg_match_ms", 0.0)
                - capture_timing.get("lossless_evaluation_total_ms", 0.0),
                2,
            )
            try:
                await self._persist_capture_diagnostic(page)
            except (PlaywrightError, PlaywrightTimeoutError, TimeoutError):
                pass

    async def detect_state(self, page: Page) -> PageState:
        current_content_id = self.content_id_from_url(page.url)
        if (
            self._initial_content_id is not None
            and current_content_id is not None
            and current_content_id != self._initial_content_id
        ):
            return PageState.NEXT_CONTENT

        if await self._visible(page.locator("#eobNext")):
            return PageState.NEXT_CONTENT
        # Some readers render a BookWalker logo canvas after the final page
        # while keeping the page counter at N/N. Once the runner has already
        # sent the next-page action from N/N, that following screen must never
        # be captured as content, even when #endOfBook is absent.
        if self._final_navigation_pending and await self._is_last_page_counter(page):
            return PageState.END
        if await self._visible(page.locator("[data-ad], .ad, #ad, #advertisement")):
            return PageState.AD
        if await self._visible(page.locator("#endOfBook")):
            return PageState.END
        if await self._visible(page.locator("#loaderStatusDialog")):
            return PageState.LOADING
        if await self._renderer_ready(page):
            if await self._last_page_end_marker_visible(page):
                return PageState.END
            terminal_ad, terminal_debug = await self._terminal_ad_state(page)
            if terminal_ad:
                # The role is intentionally tied to the current native
                # artifact.  The existing END/final-navigation checks above
                # remain authoritative for N/N after the final action.
                self._capture_debug["bookwalker_capture"]["terminal_ad"] = (
                    terminal_debug
                )
                return PageState.AD
            return PageState.CONTENT
        return PageState.UNKNOWN

    async def get_capture_target(self, page: Page) -> Locator:
        target = await self._visible_canvas(page)
        if target is None:
            raise LookupError("BookWalker content canvas is not visible")
        return target

    async def _page_draw_rectangles(
        self,
        page: Page,
        canvas: Locator,
    ) -> list[dict[str, int]]:
        trace_id = await canvas.get_attribute("data-bookwalker-trace-id")
        if not trace_id:
            return []
        size = await canvas.evaluate(
            "element => ({width: element.width, height: element.height})"
        )
        calls = await page.evaluate(
            """
            traceId => (window.__bookwalkerDrawCalls || [])
              .filter(call => call.canvasId === traceId)
              .map(call => call.destination)
            """,
            trace_id,
        )
        width = int(size["width"])
        height = int(size["height"])
        candidates: list[dict[str, int]] = []
        for values in calls:
            if not isinstance(values, list) or len(values) != 4:
                continue
            x, y, box_width, box_height = (round(float(value)) for value in values)
            left = max(0, x)
            top = max(0, y)
            right = min(width, x + box_width)
            bottom = min(height, y + box_height)
            if right - left < 100 or bottom - top < 100:
                continue
            candidates.append(
                {
                    "x": left,
                    "y": top,
                    "width": right - left,
                    "height": bottom - top,
                }
            )

        unique: list[dict[str, int]] = []
        for candidate in candidates:
            if candidate in unique:
                continue
            unique.append(candidate)

        # A transition can draw a previous page and then the current page on
        # the same canvas. Keep the largest containing rectangle and discard
        # the smaller one; side-by-side pages are not contained and survive.
        filtered: list[dict[str, int]] = []
        for candidate in sorted(
            unique,
            key=lambda box: box["width"] * box["height"],
            reverse=True,
        ):
            contained = any(
                other["x"] <= candidate["x"]
                and other["y"] <= candidate["y"]
                and other["x"] + other["width"]
                >= candidate["x"] + candidate["width"]
                and other["y"] + other["height"]
                >= candidate["y"] + candidate["height"]
                for other in filtered
            )
            if not contained:
                filtered.append(candidate)
        return sorted(filtered, key=lambda box: box["x"], reverse=True)

    async def _is_first_page(self, page: Page) -> bool:
        """Return whether the viewer is showing the first numbered page."""

        counter = page.locator("#pageSliderCounter")
        try:
            if not await counter.count():
                return False
            raw_counter = await asyncio.wait_for(
                counter.inner_text(timeout=1000), timeout=1
            )
        except (PlaywrightTimeoutError, TimeoutError):
            return False
        page_number, _page_id = self.parse_page_counter(raw_counter)
        return page_number == 1

    @staticmethod
    def _union_capture_box(boxes: list[dict[str, int]]) -> dict[str, int]:
        """Return one box covering multiple visual parts of the cover."""

        left = min(box["x"] for box in boxes)
        top = min(box["y"] for box in boxes)
        right = max(box["x"] + box["width"] for box in boxes)
        bottom = max(box["y"] + box["height"] for box in boxes)
        return {
            "x": left,
            "y": top,
            "width": right - left,
            "height": bottom - top,
        }

    async def _non_white_capture_box(
        self,
        canvas: Locator,
    ) -> dict[str, int] | None:
        """Find the visible cover bounds when draw tracing missed a frame."""

        try:
            result = await canvas.evaluate(
                """
                element => {
                  const width = element.width;
                  const height = element.height;
                  const context = element.getContext('2d', {
                    willReadFrequently: true,
                  });
                  if (!context || width <= 0 || height <= 0) return null;
                  let pixels;
                  try {
                    pixels = context.getImageData(0, 0, width, height).data;
                  } catch (error) {
                    return null;
                  }
                  let left = width;
                  let top = height;
                  let right = 0;
                  let bottom = 0;
                  for (let y = 0; y < height; y += 1) {
                    for (let x = 0; x < width; x += 1) {
                      const offset = (y * width + x) * 4;
                      const alpha = pixels[offset + 3];
                      const nonWhite = alpha > 0 && (
                        pixels[offset] < 250 ||
                        pixels[offset + 1] < 250 ||
                        pixels[offset + 2] < 250
                      );
                      if (!nonWhite) continue;
                      left = Math.min(left, x);
                      top = Math.min(top, y);
                      right = Math.max(right, x + 1);
                      bottom = Math.max(bottom, y + 1);
                    }
                  }
                  if (left >= right || top >= bottom) return null;
                  return {
                    x: left,
                    y: top,
                    width: right - left,
                    height: bottom - top,
                  };
                }
                """
            )
        except (PlaywrightError, PlaywrightTimeoutError, TimeoutError):
            return None
        if not isinstance(result, dict):
            return None
        try:
            box = {
                "x": int(result["x"]),
                "y": int(result["y"]),
                "width": int(result["width"]),
                "height": int(result["height"]),
            }
        except (KeyError, TypeError, ValueError):
            return None
        if box["width"] <= 0 or box["height"] <= 0:
            return None
        return box

    async def get_capture_targets(self, page: Page) -> tuple[Locator, ...]:
        """Return one page target, or a right-to-left split of a spread.

        BookWalker renders a novel spread into one canvas when the browser
        window is wide enough. The viewer's reading order is right page then
        left page, so temporary canvases are created in that order. Draw
        geometry is used to remove the viewer margins before Core captures.
        """

        self._capture_debug["bookwalker_capture"]["returned_path"] = "rendered_canvas"
        canvas = await self.get_capture_target(page)
        size = await canvas.evaluate(
            "element => ({width: element.width, height: element.height})"
        )
        width = int(size["width"])
        height = int(size["height"])
        boxes = await self._page_draw_rectangles(page, canvas)
        first_page = await self._is_first_page(page)
        if len(boxes) > 1 and first_page:
            # A cover spread is one visual cover. Keep it as one artifact while
            # removing the outer viewer margins; regular spreads remain
            # separate right-to-left page captures.
            boxes = [self._union_capture_box(boxes)]
        if not boxes:
            if height <= 0 or width <= height * self.spread_ratio:
                return (canvas,)
            if first_page:
                # The initial cover frame can be painted before the draw hook
                # records its geometry. Use the rendered pixel bounds as a
                # last-resort crop instead of preserving the viewer margins.
                cover_box = await self._non_white_capture_box(canvas)
                if cover_box is None:
                    return (canvas,)
                boxes = [cover_box]
            else:
                boxes = [
                    {"x": 0, "y": 0, "width": width // 2, "height": height},
                    {
                        "x": width // 2,
                        "y": 0,
                        "width": width - width // 2,
                        "height": height,
                    },
                ]

        if len(boxes) == 1 and boxes[0] == {
            "x": 0,
            "y": 0,
            "width": width,
            "height": height,
        }:
            return (canvas,)

        self._capture_run += 1
        run = f"{id(self)}-{self._capture_run}"
        await canvas.evaluate(
            """
            (source, payload) => {
              const {run, boxes} = payload;
              document
                .querySelectorAll('canvas[data-bookwalker-capture-run]')
                .forEach(element => element.remove());
              for (const box of boxes) {
                const target = document.createElement('canvas');
                window.__bookwalkerMarkInternalCanvas?.(target);
                target.width = box.width;
                target.height = box.height;
                target.dataset.bookwalkerCaptureRun = run;
                const context = target.getContext('2d');
                if (!context) throw new Error('2D canvas context unavailable');
                context.drawImage(
                  source,
                  box.x, box.y, box.width, box.height,
                  0, 0, box.width, box.height,
                );
                document.body.appendChild(target);
              }
            }
            """,
            {"run": run, "boxes": boxes},
        )
        parts = page.locator(f'canvas[data-bookwalker-capture-run="{run}"]')
        if await parts.count() != len(boxes):
            raise LookupError("BookWalker page crop did not create expected canvases")
        return tuple(parts.nth(index) for index in range(len(boxes)))

    async def cleanup_capture_targets(self, page: Page) -> None:
        await page.locator("canvas[data-bookwalker-capture-run]").evaluate_all(
            "elements => elements.forEach(element => element.remove())"
        )
        await page.evaluate(
            "() => { window.__bookwalkerDrawCalls = []; "
            "window.__bookwalkerResetTransformTrace?.(); }"
        )

    async def get_content_identity(self, page: Page) -> ContentIdentity:
        counter = page.locator("#pageSliderCounter")
        raw_counter = ""
        if await counter.count():
            try:
                raw_counter = (
                    await asyncio.wait_for(counter.inner_text(timeout=1000), timeout=1)
                ).strip()
            except (PlaywrightTimeoutError, TimeoutError):
                raw_counter = ""
        page_number, page_id = self.parse_page_counter(raw_counter)
        content_id = self.content_id_from_url(page.url)
        return ContentIdentity(
            page_id=page_id or content_id,
            page_number=page_number,
            source_id=content_id,
        )

    async def get_content_context(self, page: Page) -> ContentContext:
        content_id = self.content_id_from_url(page.url)
        title = ""
        title_locator = page.locator("#pagetitle")
        if await title_locator.count():
            try:
                title = (
                    await asyncio.wait_for(title_locator.inner_text(timeout=1000), timeout=1)
                ).strip() or None
            except (PlaywrightTimeoutError, TimeoutError):
                title = None
        return ContentContext(content_id=content_id, work_id=content_id, title=title)

    async def go_next(self, page: Page) -> None:
        try:
            previous_identity = await self.get_content_identity(page)
        except AttributeError:
            previous_identity = None
        current, total, _counter = await self._read_page_counter_pair(page)
        if (
            current is not None
            and total is not None
            and total > 1
            and current in {total - 1, total}
        ):
            self._terminal_skip_identity = previous_identity
        else:
            self._terminal_skip_identity = None
        self._final_navigation_pending = await self._is_last_page_counter(page)
        # The viewer's keyboard handler advances reliably even when a
        # viewport click is accepted by Playwright but ignored by the viewer.
        await self._press_left_arrow(page)

    async def _press_left_arrow(self, page: Page) -> None:
        await self._arm_native_capture(page)
        await page.keyboard.press("ArrowLeft")

    async def _click_left_edge(self, page: Page) -> None:
        """Use the viewer click area only after keyboard navigation stalls."""

        await self._arm_native_capture(page)
        viewport = page.locator("#viewport1")
        box = await viewport.bounding_box()
        if not box or box["width"] <= 0 or box["height"] <= 0:
            return
        try:
            await viewport.click(
                position={
                    "x": min(50, box["width"] / 10),
                    "y": box["height"] / 2,
                },
                force=True,
                timeout=1_000,
                no_wait_after=True,
            )
        except PlaywrightTimeoutError:
            return

    async def wait_for_change(
        self,
        page: Page,
        previous_identity: ContentIdentity | None,
    ) -> None:
        deadline_ms = self.page_change_timeout_ms
        elapsed_ms = 0
        retry_at_ms = self.advance_retry_interval_ms
        retry_count = 0
        while elapsed_ms < deadline_ms:
            state = await self.detect_state(page)
            can_retry_advance = False
            if state in {PageState.END, PageState.NEXT_CONTENT}:
                self._terminal_skip_identity = None
                return
            if state is PageState.AD:
                current = await self.get_content_identity(page)
                if (
                    self._terminal_skip_identity is None
                    or current != self._terminal_skip_identity
                ):
                    self._terminal_skip_identity = None
                    return
                can_retry_advance = True
            if state is PageState.CONTENT:
                current = await self.get_content_identity(page)
                if self._terminal_skip_identity is not None:
                    if current == self._terminal_skip_identity:
                        can_retry_advance = True
                    else:
                        self._terminal_skip_identity = None
                        await self._wait_for_render_ready(page)
                        return
                elif previous_identity is None:
                    return
                elif current != previous_identity:
                    self._terminal_skip_identity = None
                    await self._wait_for_render_ready(page)
                    return
                # Some BookWalker trial readers keep the final content canvas
                # at N/N after the last left-side action and never expose the
                # optional #endOfBook marker. The last page was already
                # captured before this wait, so an unchanged N/N is a safe
                # terminal condition and avoids retrying forever.
                if await self._is_last_page_counter(page):
                    return
                can_retry_advance = True
            if (
                can_retry_advance
                and retry_count < self.advance_retry_count
                and elapsed_ms >= retry_at_ms
            ):
                # Playwright can report a successful dispatch even when the
                # viewer ignores that action. Alternate the two known input
                # paths while the page identity remains authoritative.
                if retry_count % 2 == 0:
                    await self._click_left_edge(page)
                else:
                    await self._press_left_arrow(page)
                retry_count += 1
                retry_at_ms = self.advance_retry_interval_ms * (retry_count + 1)
            await page.wait_for_timeout(100)
            elapsed_ms += 100
        raise PageChangeTimeoutError("BookWalker page did not change within timeout")
