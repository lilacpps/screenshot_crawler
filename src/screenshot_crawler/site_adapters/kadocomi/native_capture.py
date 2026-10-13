"""Bounded native WebP capture proof for Kadocomi's observed canvas reader."""

from __future__ import annotations

import struct

from screenshot_crawler.core.capture import CaptureResult

MAX_NATIVE_BLOB_BYTES = 4 * 1024 * 1024
MAX_NATIVE_PIXEL_COUNT = 20_000_000
MAX_NATIVE_TOTAL_PIXEL_COUNT = 8_000_000


def capture_kadocomi_webp(
    data: bytes,
    *,
    source_mime_type: str,
    width: int,
    height: int,
) -> CaptureResult | None:
    """Describe a proven WebP Blob without decoding or rewriting its bytes.

    The browser-side capture proof compares decoded source and canvas RGBA
    pixels. This helper performs the final bounded container and metadata
    checks before returning the original Blob bytes unchanged.
    """

    if (
        not isinstance(data, bytes)
        or not 12 <= len(data) <= MAX_NATIVE_BLOB_BYTES
        or data[:4] != b"RIFF"
        or data[8:12] != b"WEBP"
        or struct.unpack_from("<I", data, 4)[0] != len(data) - 8
        or source_mime_type not in {"", "image/webp"}
        or isinstance(width, bool)
        or isinstance(height, bool)
        or not isinstance(width, int)
        or not isinstance(height, int)
        or width <= 0
        or height <= 0
        or width * height > MAX_NATIVE_PIXEL_COUNT
    ):
        return None
    return CaptureResult(
        data=data,
        width=width,
        height=height,
        mime_type="image/webp",
        file_extension=".webp",
    )


NATIVE_OBSERVER_INIT_SCRIPT = r"""(() => {
  const key = '__kadocomiNativeCaptureV1';
  if (window[key]) return;
  const maxBlobCount = 64;
  const maxBlobBytes = 16 * 1024 * 1024;
  const maxSingleBlobBytes = 4 * 1024 * 1024;
  const state = {
    blobs: new Map(),
    blobBytes: 0,
    canvasIds: new WeakMap(),
    slideIds: new WeakMap(),
    nextCanvasId: 0,
    nextSlideId: 0,
    originalCreateObjectURL: URL.createObjectURL,
    originalDrawImage: CanvasRenderingContext2D.prototype.drawImage,
    originalMutators: new Map(),
    hooksInstalled: false
  };
  const originalCreate = state.originalCreateObjectURL;
  const originalDraw = state.originalDrawImage;
  const createHook = function(object) {
    const url = Reflect.apply(originalCreate, URL, [object]);
    if (object instanceof Blob && (object.type === '' || object.type === 'image/webp') &&
        object.size > 0 && object.size <= maxSingleBlobBytes &&
        state.blobs.size < maxBlobCount && state.blobBytes + object.size <= maxBlobBytes) {
      const prior = state.blobs.get(url);
      if (prior) state.blobBytes -= prior.size;
      state.blobs.set(url, {blob: object, size: object.size, type: object.type});
      state.blobBytes += object.size;
    }
    return url;
  };
  URL.createObjectURL = createHook;
  const drawHook = function(source, ...args) {
    const canvas = this.canvas;
    const isCanvas = canvas instanceof HTMLCanvasElement;
    const sourceIsImage = source instanceof HTMLImageElement;
    let draw = null;
    if (isCanvas) {
      const sourceUrl = sourceIsImage ? (source.currentSrc || '') : '';
      const entry = sourceUrl ? state.blobs.get(sourceUrl) : null;
      const transform = this.getTransform();
      const naturalWidth = sourceIsImage ? source.naturalWidth : 0;
      const naturalHeight = sourceIsImage ? source.naturalHeight : 0;
      const rect = args.map(value => Number(value));
      let sourceRect = null;
      let destinationRect = null;
      if (rect.length === 2) {
        sourceRect = [0, 0, naturalWidth, naturalHeight];
        destinationRect = [rect[0], rect[1], naturalWidth, naturalHeight];
      } else if (rect.length === 4) {
        sourceRect = [0, 0, naturalWidth, naturalHeight];
        destinationRect = rect;
      } else if (rect.length === 8) {
        sourceRect = rect.slice(0, 4);
        destinationRect = rect.slice(4, 8);
      }
      draw = {
        sourceTag: sourceIsImage ? 'IMG' : (source && source.tagName) || '',
        sourceUrl,
        sourceWidth: naturalWidth,
        sourceHeight: naturalHeight,
        blobAvailable: !!entry,
        blobType: entry ? entry.type : null,
        rect: sourceRect && destinationRect ? sourceRect.concat(destinationRect) : null,
        transform: [transform.a, transform.b, transform.c, transform.d, transform.e, transform.f],
        globalAlpha: this.globalAlpha,
        compositeOperation: this.globalCompositeOperation,
        filter: this.filter,
        complete: sourceIsImage && source.complete,
        sourceIsImage
      };
    }
    const result = Reflect.apply(originalDraw, this, [source, ...args]);
    if (isCanvas) {
      const previous = this.canvas && state.draws.get(this.canvas);
      state.draws.set(this.canvas, {
        count: previous ? previous.count + 1 : 1,
        mutationCount: state.mutationCounts.get(this.canvas) || 0,
        last: draw
      });
    }
    return result;
  };
  state.draws = new WeakMap();
  state.mutationCounts = new WeakMap();
  CanvasRenderingContext2D.prototype.drawImage = drawHook;
  const mutators = ['clearRect', 'fillRect', 'strokeRect', 'putImageData'];
  for (const name of mutators) {
    const original = CanvasRenderingContext2D.prototype[name];
    if (typeof original !== 'function') continue;
    state.originalMutators.set(name, original);
    CanvasRenderingContext2D.prototype[name] = function(...args) {
      const canvas = this.canvas;
      const result = Reflect.apply(original, this, args);
      if (canvas instanceof HTMLCanvasElement) {
        state.mutationCounts.set(canvas, (state.mutationCounts.get(canvas) || 0) + 1);
      }
      return result;
    };
  }
  state.hooksInstalled = URL.createObjectURL === createHook &&
    CanvasRenderingContext2D.prototype.drawImage === drawHook &&
    mutators.every(name => state.originalMutators.has(name));
  state.idForCanvas = canvas => {
    if (!state.canvasIds.has(canvas)) state.canvasIds.set(canvas, `canvas-${++state.nextCanvasId}`);
    return state.canvasIds.get(canvas);
  };
  state.idForSlide = slide => {
    if (!state.slideIds.has(slide)) state.slideIds.set(slide, `slide-${++state.nextSlideId}`);
    return state.slideIds.get(slide);
  };
  const hasClassPrefix = (node, prefix) => [...node.classList].some(name => name.startsWith(prefix));
  // Observed first-page variant: one directly typed canvas on the first slide.
  // Every other content node must retain the usual wrapper contract.
  state.contentCanvasRow = (node, firstSlide) => {
    if (node.tagName === 'DIV' && hasClassPrefix(node, '_pageCanvasWrapper_'))
      return [...node.querySelectorAll('canvas')];
    if (node.tagName === 'CANVAS' && hasClassPrefix(node, '_root_bx4cr_') &&
        node.closest('.splide__slide') === firstSlide &&
        firstSlide.querySelectorAll('[data-type="contents"]').length === 1)
      return [node];
    return null;
  };
  state.snapshot = (includeNodes = false) => {
    const screens = [...document.querySelectorAll('._mainScreen_191o7_1')];
    if (screens.length !== 1) return {status: 'root', screenCount: screens.length};
    const roots = [...screens[0].querySelectorAll('.splide._root_1542n_1')];
    if (roots.length !== 1) return {status: 'root', screenCount: 1, rootCount: roots.length};
    const root = roots[0];
    const rootsNested = [...root.querySelectorAll('.splide')];
    if (rootsNested.length !== 0) return {status: 'nested_carousel'};
    const slides = [...root.querySelectorAll('.splide__slide')];
    const clones = slides.filter(slide => slide.classList.contains('splide__slide--clone'));
    const active = slides.filter(slide => slide.classList.contains('is-active'));
    if (!slides.length || active.length !== 1) {
      return {status: 'slides', slideCount: slides.length, activeCount: active.length,
        cloneCount: clones.length};
    }
    if (clones.length) return {status: 'clones', cloneCount: clones.length};
    if (!root.classList.contains('splide--rtl')) return {status: 'direction'};
    const allContentNodes = [...root.querySelectorAll('[data-type="contents"]')];
    const contentWrappers = allContentNodes;
    const wrapperCanvasRows = contentWrappers.map(node => state.contentCanvasRow(node, slides[0]));
    if (wrapperCanvasRows.some(row => row === null)) return {status: 'content_wrapper_shape'};
    const wrapperCanvasCount = wrapperCanvasRows.reduce((total, canvases) => total + canvases.length, 0);
    if (wrapperCanvasRows.some(canvases =>
      canvases.length !== 1 || !hasClassPrefix(canvases[0], '_root_bx4cr_'))) {
      return {status: wrapperCanvasCount === 0 ? 'content_loading' : 'content_wrapper_shape'};
    }
    const allEndNodes = [...root.querySelectorAll('div[data-type="end-of-book"]')];
    const markers = allEndNodes.filter(node => hasClassPrefix(node, '_endOfBookWrapper_'));
    const secondaryEndNodes = allEndNodes.filter(node =>
      !hasClassPrefix(node, '_endOfBookWrapper_') && hasClassPrefix(node, '_endOfBook_'));
    const unclassifiedEndMarkerCount = allEndNodes.length - markers.length - secondaryEndNodes.length;
    const slideRows = slides.map((slide, slideIndex) => {
      const wrappers = [...slide.querySelectorAll('[data-type="contents"]')];
      const canvases = wrappers.map(node => state.contentCanvasRow(node, slides[0])[0]);
      return {
        id: state.idForSlide(slide),
        index: slideIndex,
        active: slide === active[0],
        box: (() => {
          const rect = slide.getBoundingClientRect();
          return {x: rect.x, y: rect.y, width: rect.width, height: rect.height};
        })(),
        contentSlots: canvases.filter(Boolean).map(canvas => state.idForCanvas(canvas)),
        contentCanvases: canvases.filter(Boolean).map((canvas, canvasIndex) => {
          const record = state.draws.get(canvas);
          const last = record && record.last;
          const entry = last && last.sourceUrl ? state.blobs.get(last.sourceUrl) : null;
          return {
            slot: state.idForCanvas(canvas),
            wrapperClass: wrappers[canvasIndex].className,
            width: canvas.width,
            height: canvas.height,
            box: (() => {
              const rect = canvas.getBoundingClientRect();
              return {x: rect.x, y: rect.y, width: rect.width, height: rect.height};
            })(),
            drawCount: record ? record.count : 0,
            mutationCount: state.mutationCounts.get(canvas) || 0,
            last: last ? {
              sourceTag: last.sourceTag,
              sourceUrl: last.sourceUrl,
              sourceWidth: last.sourceWidth,
              sourceHeight: last.sourceHeight,
              blobAvailable: !!entry,
              blobType: entry ? entry.type : null,
              rect: last.rect,
              transform: last.transform,
              globalAlpha: last.globalAlpha,
              compositeOperation: last.compositeOperation,
              filter: last.filter,
              complete: last.complete
            } : null
          };
        })
      };
    });
    const contentOutsideSlides = contentWrappers
      .filter(wrapper => !wrapper.closest('.splide__slide')).length;
    const markerSlideIndexes = markers.map(marker => slides.indexOf(marker.closest('.splide__slide')));
    const markerNumbers = markers.map(marker => marker.getAttribute('data-n'));
    const secondaryEndMarkerSlideIndexes = secondaryEndNodes.map(marker =>
      slides.indexOf(marker.closest('.splide__slide')));
    const markerBox = node => {
      const owner = node.closest('.splide__slide');
      if (!owner) return null;
      const ownerRect = owner.getBoundingClientRect();
      const rect = node.getBoundingClientRect();
      return {
        x: rect.x - ownerRect.x,
        y: rect.y - ownerRect.y,
        width: rect.width,
        height: rect.height,
        slideWidth: ownerRect.width,
        slideHeight: ownerRect.height
      };
    };
    const beginningNodes = [...root.querySelectorAll('div[data-type="beginning"]')];
    const prNodes = [...root.querySelectorAll('div[data-type="pr"]')];
    const beginningMarkers = beginningNodes.map(node => {
      const owner = node.closest('.splide__slide');
      return {
        tagName: node.tagName,
        rootClass: hasClassPrefix(node, '_root_1w5tt_'),
        dataType: node.getAttribute('data-type'),
        dataN: node.getAttribute('data-n'),
        slideIndex: slides.indexOf(owner),
        box: markerBox(node),
        prMarkerCount: [...node.querySelectorAll('div[data-type="pr"]')].length
      };
    });
    const prMarkers = prNodes.map(node => {
      const owner = node.closest('.splide__slide');
      const beginning = node.closest('div[data-type="beginning"]');
      return {
        tagName: node.tagName,
        wrapperClass: hasClassPrefix(node, '_endOfBookWrapper_'),
        secondaryClass: hasClassPrefix(node, '_endOfBook_'),
        dataType: node.getAttribute('data-type'),
        dataN: node.getAttribute('data-n'),
        slideIndex: slides.indexOf(owner),
        beginningOwnerIndex: beginning
          ? slides.indexOf(beginning.closest('.splide__slide')) : -1,
        box: markerBox(node)
      };
    });
    const markerRecord = node => {
      const owner = node.closest('.splide__slide');
      const ownerRect = owner ? owner.getBoundingClientRect() : null;
      const rect = node.getBoundingClientRect();
      return {
        tagName: node.tagName,
        wrapperClass: hasClassPrefix(node, '_endOfBookWrapper_'),
        secondaryClass: hasClassPrefix(node, '_endOfBook_'),
        dataType: node.getAttribute('data-type'),
        dataN: node.getAttribute('data-n'),
        slideIndex: slides.indexOf(owner),
        box: ownerRect ? {
          x: rect.x - ownerRect.x,
          y: rect.y - ownerRect.y,
          width: rect.width,
          height: rect.height,
          slideWidth: ownerRect.width,
          slideHeight: ownerRect.height
        } : null
      };
    };
    const mainEndMarkers = markers.map(markerRecord);
    const secondaryEndMarkers = secondaryEndNodes.map(markerRecord);
    const activeIndex = slides.indexOf(active[0]);
    if (unclassifiedEndMarkerCount > 0) return {status: 'end_marker_shape'};
    return {
      status: 'ok',
      directFirstContent: allContentNodes.some(node => node.tagName === 'CANVAS'),
      directFirstBeginningOwnerIndex: (() => {
        const canvas = allContentNodes.find(node => node.tagName === 'CANVAS');
        const beginning = canvas && canvas.closest('div[data-type="beginning"]');
        return beginning ? slides.indexOf(beginning.closest('.splide__slide')) : -1;
      })(),
      rootId: state.idForSlide(root),
      slideRows,
      activeIndex,
      direction: getComputedStyle(root).direction,
      rtlClass: root.classList.contains('splide--rtl'),
      contentOutsideSlides,
      endMarkerCount: markers.length,
      markerSlideIndexes,
      markerNumbers,
      mainEndMarkers,
      secondaryEndMarkerSlideIndexes,
      secondaryEndMarkers,
      beginningMarkerCount: beginningMarkers.length,
      beginningMarkers,
      prMarkerCount: prMarkers.length,
      prMarkers,
      unclassifiedEndMarkerCount,
      hooksInstalled: state.hooksInstalled,
      ...(includeNodes ? {root} : {})
    };
  };
  window[key] = state;
})();"""


NATIVE_CAPTURE_SCRIPT = r"""async args => {
  const state = window.__kadocomiNativeCaptureV1;
  const fail = reason => ({ok: false, reason});
  if (!state || !state.hooksInstalled) return fail('hooks_missing');
  if (!Number.isInteger(args.maxBytes) || args.maxBytes <= 0 ||
      !Number.isInteger(args.maxPixels) || args.maxPixels <= 0 ||
      !Number.isInteger(args.maxTotalPixels) || args.maxTotalPixels <= 0)
    return fail('invalid_capture_budget');
  const first = state.snapshot(true);
  if (first.status !== 'ok' || first.contentOutsideSlides !== 0) return fail('reader_changed');
  const slides = [...first.root.querySelectorAll('.splide__slide')];
  const active = slides[first.activeIndex];
  if (!active) return fail('active_slide_missing');
  const typedContent = [...active.querySelectorAll('[data-type="contents"]')];
  const canvasRows = typedContent.map(node => state.contentCanvasRow(node, slides[0]));
  if (canvasRows.some(row => row === null || row.length !== 1 ||
      ![...row[0].classList].some(name => name.startsWith('_root_bx4cr_'))))
    return fail('content_wrapper_shape');
  const canvases = canvasRows.map(row => row[0]);
  const currentSlots = canvases.map(canvas => state.idForCanvas(canvas));
  if (JSON.stringify(currentSlots) !== JSON.stringify(args.expectedSlots)) return fail('slot_identity_changed');
  const captures = [];
  const usedUrls = [];
  let totalPixels = 0;
  const signature = snapshot => JSON.stringify({
    directFirstContent: snapshot.directFirstContent,
    directFirstBeginningOwnerIndex: snapshot.directFirstBeginningOwnerIndex,
    activeIndex: snapshot.activeIndex,
    endMarkerCount: snapshot.endMarkerCount,
    markerSlideIndexes: snapshot.markerSlideIndexes,
    markerNumbers: snapshot.markerNumbers,
    mainEndMarkers: snapshot.mainEndMarkers,
    secondaryEndMarkerSlideIndexes: snapshot.secondaryEndMarkerSlideIndexes,
    secondaryEndMarkers: snapshot.secondaryEndMarkers,
    beginningMarkerCount: snapshot.beginningMarkerCount,
    beginningMarkers: snapshot.beginningMarkers,
    prMarkerCount: (args.trackPrMarkers === true || snapshot.beginningMarkerCount > 0)
      ? snapshot.prMarkerCount : 0,
    prMarkers: (args.trackPrMarkers === true || snapshot.beginningMarkerCount > 0)
      ? snapshot.prMarkers : [],
    slideRows: snapshot.slideRows.map(row => ({
      id: row.id,
      index: row.index,
      active: row.active,
      box: row.box,
      contentCanvases: row.contentCanvases
    }))
  });
  for (const [index, canvas] of canvases.entries()) {
    const slot = currentSlots[index];
    const ctx = canvas.getContext('2d', {willReadFrequently: true});
    const record = state.draws.get(canvas);
    const draw = record && record.last;
    if (!ctx || !draw || draw.sourceTag !== 'IMG' || !draw.sourceIsImage || !draw.complete)
      return fail('image_draw_missing');
    const entry = state.blobs.get(draw.sourceUrl);
    if (!entry || !draw.sourceUrl || !draw.sourceUrl.startsWith('blob:')) return fail('blob_mapping_missing');
    const width = canvas.width, height = canvas.height;
    if (!width || !height || width * height > args.maxPixels ||
        draw.sourceWidth !== width || draw.sourceHeight !== height) return fail('dimensions_mismatch');
    totalPixels += width * height;
    if (totalPixels > args.maxTotalPixels) return fail('capture_pixel_budget_exceeded');
    const expectedRect = [0, 0, width, height, 0, 0, width, height];
    if (!draw.rect || JSON.stringify(draw.rect) !== JSON.stringify(expectedRect)) return fail('draw_not_full_frame');
    if (!draw.transform || JSON.stringify(draw.transform) !== '[1,0,0,1,0,0]' ||
        draw.globalAlpha !== 1 || draw.compositeOperation !== 'source-over' || draw.filter !== 'none')
      return fail('draw_state_unsupported');
    if (record.mutationCount !== (state.mutationCounts.get(canvas) || 0))
      return fail('canvas_mutated_after_image_draw');
    if (entry.size > args.maxBytes) return fail('blob_too_large');
    let before;
    try { before = ctx.getImageData(0, 0, width, height).data; }
    catch (_) { return fail('canvas_pixels_unavailable'); }
    let bitmap;
    let sourcePixels;
    let stableDrawKey;
    try { bitmap = await createImageBitmap(entry.blob); }
    catch (_) { return fail('blob_decode_failed'); }
    try {
      if (bitmap.width !== width || bitmap.height !== height) return fail('decoded_dimensions_mismatch');
      const scratch = document.createElement('canvas');
      scratch.width = width; scratch.height = height;
      const scratchContext = scratch.getContext('2d', {willReadFrequently: true});
      if (!scratchContext) return fail('scratch_context_missing');
      scratchContext.drawImage(bitmap, 0, 0);
      sourcePixels = scratchContext.getImageData(0, 0, width, height).data;
      const after = ctx.getImageData(0, 0, width, height).data;
      if (before.length !== after.length || sourcePixels.length !== after.length) return fail('pixel_length_mismatch');
      for (let pixel = 0; pixel < after.length; pixel += 1) {
        if (sourcePixels[pixel] !== after[pixel] || before[pixel] !== after[pixel]) return fail('pixel_mismatch_or_canvas_changed');
      }
      const bytes = new Uint8Array(await entry.blob.arrayBuffer());
      if (bytes.length !== entry.size || bytes.length > args.maxBytes) return fail('blob_size_changed');
      let binary = '';
      for (let offset = 0; offset < bytes.length; offset += 0x8000) {
        binary += String.fromCharCode(...bytes.subarray(offset, offset + 0x8000));
      }
      captures.push({slot, width, height, mimeType: entry.type, data: btoa(binary)});
      stableDrawKey = JSON.stringify({
        count: record.count,
        sourceUrl: draw.sourceUrl,
        mutationCount: record.mutationCount,
        sourceWidth: draw.sourceWidth,
        sourceHeight: draw.sourceHeight,
        rect: draw.rect,
        transform: draw.transform,
        globalAlpha: draw.globalAlpha,
        compositeOperation: draw.compositeOperation,
        filter: draw.filter
      });
      usedUrls.push({url: draw.sourceUrl, size: entry.size});
      captures[captures.length - 1].proof = {
        canvas,
        ctx,
        width,
        height,
        sourcePixels,
        stableDrawKey,
        sourceUrl: draw.sourceUrl,
        blob: entry.blob,
        mutationCount: record.mutationCount
      };
    } finally {
      bitmap.close();
    }
  }
  const last = state.snapshot(true);
  if (last.status !== 'ok' || last.rootId !== first.rootId ||
      last.activeIndex !== first.activeIndex ||
      last.endMarkerCount !== first.endMarkerCount ||
      JSON.stringify(last.markerNumbers) !== JSON.stringify(first.markerNumbers) ||
      JSON.stringify(last.mainEndMarkers) !== JSON.stringify(first.mainEndMarkers) ||
      JSON.stringify(last.secondaryEndMarkerSlideIndexes) !== JSON.stringify(first.secondaryEndMarkerSlideIndexes) ||
      JSON.stringify(last.secondaryEndMarkers) !== JSON.stringify(first.secondaryEndMarkers) ||
      last.beginningMarkerCount !== first.beginningMarkerCount ||
      JSON.stringify(last.beginningMarkers) !== JSON.stringify(first.beginningMarkers) ||
      ((args.trackPrMarkers === true || first.beginningMarkerCount > 0) &&
        (last.prMarkerCount !== first.prMarkerCount ||
         JSON.stringify(last.prMarkers) !== JSON.stringify(first.prMarkers))) ||
      JSON.stringify(last.slideRows.map(row => [row.id, row.contentSlots])) !==
      JSON.stringify(first.slideRows.map(row => [row.id, row.contentSlots]))) return fail('snapshot_changed');
  for (const capture of captures) {
    const proof = capture.proof;
    const record = state.draws.get(proof.canvas);
    const draw = record && record.last;
    const entry = state.blobs.get(proof.sourceUrl);
    const currentKey = record && draw ? JSON.stringify({
      count: record.count,
      sourceUrl: draw.sourceUrl,
      mutationCount: record.mutationCount,
      sourceWidth: draw.sourceWidth,
      sourceHeight: draw.sourceHeight,
      rect: draw.rect,
      transform: draw.transform,
      globalAlpha: draw.globalAlpha,
      compositeOperation: draw.compositeOperation,
      filter: draw.filter
    }) : '';
    if (!proof.canvas.isConnected || proof.canvas.width !== proof.width ||
        proof.canvas.height !== proof.height || !entry || entry.blob !== proof.blob ||
        !draw || !draw.sourceIsImage || draw.image ||
        (state.mutationCounts.get(proof.canvas) || 0) !== proof.mutationCount ||
        record.mutationCount !== proof.mutationCount ||
        draw.sourceUrl !== proof.sourceUrl || currentKey !== proof.stableDrawKey) {
      return fail('canvas_or_draw_changed');
    }
    let finalPixels;
    try { finalPixels = proof.ctx.getImageData(0, 0, proof.width, proof.height).data; }
    catch (_) { return fail('canvas_pixels_unavailable_after_read'); }
    if (finalPixels.length !== proof.sourcePixels.length) return fail('final_pixel_length_changed');
    for (let pixel = 0; pixel < finalPixels.length; pixel += 1) {
      if (finalPixels[pixel] !== proof.sourcePixels[pixel]) return fail('canvas_changed_after_async_read');
    }
    delete capture.proof;
  }
  const finalSnapshot = state.snapshot(true);
  if (finalSnapshot.status !== 'ok' || signature(finalSnapshot) !== signature(last))
    return fail('layout_or_draw_state_changed_after_async_read');
  for (const used of usedUrls) {
    const entry = state.blobs.get(used.url);
    if (entry) state.blobBytes -= used.size;
    state.blobs.delete(used.url);
  }
  return {ok: true, captures};
}"""


def source_identity_metadata(snapshot: object, slot: str) -> dict[str, object] | None:
    """Return one slot's shallow draw evidence from a validated snapshot."""

    if not isinstance(snapshot, dict):
        return None
    rows = snapshot.get("slideRows")
    if not isinstance(rows, list):
        return None
    for row in rows:
        if not isinstance(row, dict):
            continue
        canvases = row.get("contentCanvases")
        if not isinstance(canvases, list):
            continue
        for canvas in canvases:
            if isinstance(canvas, dict) and canvas.get("slot") == slot:
                last = canvas.get("last")
                return last if isinstance(last, dict) else None
    return None


__all__ = [
    "MAX_NATIVE_BLOB_BYTES",
    "MAX_NATIVE_PIXEL_COUNT",
    "MAX_NATIVE_TOTAL_PIXEL_COUNT",
    "NATIVE_CAPTURE_SCRIPT",
    "NATIVE_OBSERVER_INIT_SCRIPT",
    "capture_kadocomi_webp",
    "source_identity_metadata",
]
