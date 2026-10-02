# Capture Strategy

## 1. Purpose / authority

This document is the detailed authority for image capture selection in Screenshot Crawler.

It defines how a Site Adapter should choose the highest-fidelity safe capture path while avoiding interference with the site's renderer and navigation.

Site-specific documents may describe selectors, hosts, viewer behavior, and verified exceptions, but they should follow this priority unless a live-tested site constraint requires otherwise.

The short form is:

```text
original bytes
    ↓ unavailable / not safely attributable
source-native pixels
    ↓ unavailable / unsafe
rendered content canvas
    ↓ unavailable
Locator / viewport screenshot
```

The goal is not to force one file format across sites. The goal is to preserve the best trustworthy representation of the page with the least transformation and the least interference with the viewer.

---

## 2. Capture priority

### Level 1: Original bytes

Prefer the original image response or source file when the exact bytes corresponding to the visible page can be identified safely.

Examples:

- JPEG response used for the currently visible BookWalker page
- WebP response used for the currently visible Manga ONE page
- an image resource whose page/source identity can be matched one-to-one

Requirements:

- the candidate must correspond to the current visible page or spread part
- dimensions and page/source identity must be consistent
- ambiguous matches must not be guessed
- tiled atlases, composed layers, transforms, masks, or other rendering steps that materially change the visible result must not be treated as a direct original-image capture unless equivalence is proven
- a spread must preserve reading order

When original bytes are accepted, preserve them as-is.

Do not re-encode JPEG/WebP/PNG merely to normalize extensions or file types.

```text
JPEG -> JPEG
WebP -> WebP
PNG  -> PNG
```

A format conversion is not an improvement when the original bytes are already the correct page image.

---

### Level 2: Source-native pixels

Use source-native capture when original bytes cannot be obtained or cannot be matched safely, but the renderer's source pixels can be attributed safely to the visible page.

Typical sources include:

- `ImageBitmap`
- `HTMLCanvasElement`
- another renderer-owned pixel source whose source rectangle and composition can be verified

The capture should use the source rectangle at its native pixel dimensions rather than resizing it to the displayed canvas dimensions.

Source-native materialization should normally be stored as lossless PNG.

Required safety checks include, as applicable:

- source type
- source dimensions
- source rectangle
- destination rectangle
- transform
- composite operation
- filter
- page/spread geometry
- reading order
- one-to-one attribution between the selected draw call and the visible page part

If these cannot be verified, fall back to Level 3.

#### Immutable / stable source

For a stable source such as an `ImageBitmap`, retain only the bounded reference/metadata needed for the current capture window and materialize the selected source after the final draw call has been identified.

Do not eagerly encode every draw candidate.

#### Mutable source

For a mutable source such as an intermediate `HTMLCanvasElement`, the source may change after `drawImage()`.

In that case:

```text
drawImage
  -> copy the required source pixels into a temporary snapshot canvas
  -> return control to the viewer

after the visible draw call is selected
  -> encode the selected snapshot canvas as PNG
```

The important rule is:

> Snapshot pixels at draw time when mutability requires it, but perform PNG encoding after draw-time processing.

Do not reread the mutable source later and assume it still represents the same page.

---

### Level 3: Rendered content canvas

If source-native capture is not safely available, capture the completed content canvas after the viewer has finished rendering.

Prefer:

1. raw canvas pixels / PNG
2. a content-only canvas crop
3. a temporary canvas created from verified rendered geometry

The capture should exclude browser chrome and viewer UI when possible.

This path is appropriate when:

- multiple source images are composed
- source geometry is ambiguous
- transforms or filters prevent safe source-native extraction
- native-source tracing fails
- a site intentionally renders the final page only into a canvas

The renderer must first be stable. Capture must not race the page transition or use a partially rendered canvas.

Rendered canvas capture is a fallback, not a failure. Correct rendered pixels are preferable to an incorrectly inferred original/native source.

---

### Level 4: Locator / viewport screenshot

Use screenshot capture only when the page cannot be obtained safely from original bytes, native source pixels, or the rendered content canvas.

Preference:

```text
content Locator screenshot
    ↓ unavailable
viewport / screen screenshot
```

A Locator screenshot should exclude toolbars, navigation controls, ads, and unrelated UI where possible.

Viewport screenshot is the last resort.

---

## 3. Fidelity rules

Capture fidelity has priority over file-format uniformity.

Do not:

- convert PNG to JPEG merely to save space
- convert JPEG/WebP to PNG merely to standardize output
- upscale an image to displayed dimensions when native pixels are already available
- downscale a native image to the viewer's CSS/rendered size without a site-specific reason
- synthesize a JPEG from a rendered PNG and present it as an original image

Prefer the least transformed trustworthy representation.

A mixed archive containing original JPEG/WebP and PNG fallback artifacts is acceptable when the manifest accurately records the actual files.

---

## 4. Renderer critical-path rule

Capture logic must not make the site's renderer substantially heavier.

In particular, a `drawImage()` hook must avoid expensive synchronous work such as:

- PNG/JPEG encoding
- `toDataURL()`
- Base64 conversion
- hashing
- image signature calculation
- network work
- repeated full-image copies that are not required for mutability safety

The hook should collect only the minimum information needed to make the later capture decision.

For mutable pixel sources, one bounded pixel copy into a temporary snapshot canvas is acceptable when necessary to preserve draw-time contents. Encoding that snapshot must happen later.

This rule comes from the BookWalker live issue where synchronous PNG encoding during renderer draws caused intermittent navigation instability and `wait_for_change` failures. Moving PNG encoding after draw-call selection restored stable native capture behavior.

---

## 5. Network observation rule

Observing original image responses must not become a dependency that blocks normal viewer rendering.

Network capture should be:

- bounded
- host/resource-type limited
- tolerant of body-read failure
- safe to abandon in favor of a lower capture level

If an original response cannot be read or uniquely matched, continue with source-native or rendered capture rather than failing the crawl solely because the optimization failed.

---

## 6. Fallback policy

Fallback always moves downward in the capture hierarchy.

```text
original
  -> native
      -> rendered canvas
          -> screenshot
```

Do not move downward because of format preference alone.

Move downward when the higher level is:

- unavailable
- ambiguous
- unsafe
- incomplete
- likely to interfere with the viewer
- not proven to represent the final visible page

When a higher-level optimization fails, the lower-level path should remain simple and independently reliable.

---

## 7. Spread / multi-part policy

For a visible spread or multi-part page:

- preserve the site's reading order
- verify every part before accepting a higher capture level
- avoid mixing a verified high-level result for one side with an uncertain result for the other side

Prefer all-or-none fallback for one visible spread:

```text
both parts original
or
both parts native
or
both parts rendered fallback
```

This keeps page ordering and visual provenance predictable.

Site-specific exceptions require live verification and documentation.

---

## 8. Lifecycle and memory safety

Temporary capture state must be bounded to the current page/capture window.

Examples:

- retained source objects
- draw-call metadata
- snapshot canvases
- original-response candidates
- temporary crop canvases

Clear temporary state when:

- a new capture window is armed
- capture succeeds
- capture falls back
- the page changes
- the run ends or the Adapter is cleaned up

Do not let renderer source references or snapshot canvases accumulate across a long crawl.

---

## 9. Navigation isolation

Capture improvements must not silently change page-navigation semantics.

When investigating capture-related instability:

1. keep navigation timeout/retry behavior fixed where possible
2. compare capture implementations independently
3. use a lower-level capture mode as an A/B control when practical

A capture implementation that produces better pixels but destabilizes navigation is not acceptable.

The BookWalker `native` / `canvas` A/B switch is an example of this diagnostic pattern.

---

## 10. Validation before adopting a higher capture level

A new site should not adopt original/native capture only because a promising source was found.

Validate representative cases such as:

- first page / cover
- normal single page
- spread
- portrait and landscape pages
- transitions
- final page
- different content types if the viewer supports them
- slow-loading pages
- repeated navigation over a bounded multi-page run

For original/native capture, compare against the known-good rendered result during investigation.

The comparison may use diagnostics and temporary tooling; those diagnostics do not need to become production dependencies.

---

## 11. A/B testing guidance

When capture changes may affect viewer stability, keep a simple lower-level control path if the implementation cost is small.

For example:

```text
A: native/original capture enabled
B: rendered-canvas-only capture
```

Use the same:

- source/work
- browser profile
- viewport
- page count
- navigation behavior
- timeout/retry configuration

Compare:

- completion state
- `wait_for_change` failures
- saved page count
- skipped or duplicated pages
- fingerprints
- output dimensions
- artifact format
- transition behavior

Do not change capture and navigation timing simultaneously when the goal is root-cause isolation.

---

## 12. Current site mapping

The generic hierarchy is site-neutral. Current site implementations use different levels depending on what has been verified.

### BookWalker

Preferred path:

```text
verified original JPEG
    -> verified source-native reconstructed JPEG
    -> source-native PNG
        -> rendered canvas PNG
```

BookWalker's purchased-JPEG integration keeps the existing byte-preserving
original-JPEG candidate path first priority. When that
path does not produce a unique exact match, the adapter may validate a
clear-bounded completed renderer mapping containing the visible renderer draw,
its intermediate `HTMLCanvasElement`, a unique `ImageBitmap` tile permutation,
and a matching purchased raw JPEG. Production does not use a global operation
list as mapping authority: it retains a monotonic operation index, bounded
active segments, and bounded completed mappings. The supported shadow contract
is baseline sequential SOF0, three-component 4:4:4 JPEG, equal source/canvas
dimensions, uniform strict-MCU tiles, and a complete bijection. The helper
moves quantized DCT blocks with `jpeglib.read_dct()` / `write_dct()`, reads the
coefficients back, and verifies zero mismatches plus unchanged quantization
tables. Production reconstruction also validates the source and output DCT
layout: three components, 4:4:4 sampling, one scan, and non-progressive
baseline structure. The completed mapping records are selected by the exact
renderer `mappingId`; retained-trace counts are returned as a small numeric
summary rather than transferring the full trace.
The selected records use a versioned compact BookWalker-local transport
representation and are decoded back to the unchanged rich mapping contract
before the Python proof validator runs.

For purchased pages, a strictly proven full-frame one-hop canvas scale may
expose a higher-resolution source-native canvas. The supported shape is only:

```text
proven tile canvas A
    -> exactly one full-frame HTMLCanvasElement draw
canvas B
    -> selected renderer
```

The Python resolver connects that hop only by exact mapping ID, operation
index, canvas identity, dimensions, geometry, safe draw state, and strict
operation ordering. It does not support recursive canvas graphs, two or more
hops, nearest mappings, dimension guessing, operation-proximity guessing, or
fuzzy provenance. Reconstruction returns the source-native JPEG (for example
960x1280), not a JPEG representation of the scaled 480x640 rendered pixels;
the DCT mapping dimensions remain the proven source dimensions.
Original JPEG matching remains first priority; its retry wait is now bounded
and event-driven, and is used only while eligible response work is pending.

Phase P2/P3/P4/P5 may return the verified reconstructed JPEG only when every
production proof gate passes, including `mapping_proven=true`,
`mapping_source=completed_segment`, no segment overflow or completed-mapping
eviction, one full-resolution raw JPEG match, supported strict-MCU JPEG layout,
exact coefficients and quantization tables, output structural parity, and
the reconstructed result matching the proven mapping source dimensions. Direct
mapping additionally keeps the historical native-dimension contract; the
one-hop source-native path intentionally permits reconstructed dimensions to
differ from the displayed native PNG. The production authority is the verified
source JPEG, complete MCU-aligned mapping, coefficient-exact reconstruction,
equal quantization tables, and supported source/output JPEG structure. Browser-decoded
full-pixel equality is not a default production gate after P4-5. It remains an
optional BookWalker-local diagnostic through `BOOKWALKER_FINAL_PIXEL_VERIFY`;
when enabled, it is an additional gate and mismatch falls back to native PNG.
Direct mappings use intrinsic comparison. One-hop scaled mappings use the
proven source rectangle and destination size, including observed image
smoothing state, to compare the source-native JPEG after scaling to the native
PNG; this remains diagnostic evidence rather than production provenance
authority.
The output switch is BookWalker-local:
`BOOKWALKER_LOSSLESS_JPEG_OUTPUT` is BookWalker-local and is enabled by
default in Phase P3. Explicit `1`, `true`, `yes`, and `on` values also enable
it. The kill switch is `BOOKWALKER_LOSSLESS_JPEG_OUTPUT=0` (also `false`,
`no`, or `off`), which restores the P1/P2 shadow-only native-PNG output.
An invalid explicit value fails fast in the BookWalker adapter.

Before any full-size candidate comparison, purchased candidates are bounded
by exact `mapping.source_dimensions`, then by the existing deterministic 64x64
browser signature. The retained `ImageBitmap` is hashed with the same
`image_signature()` algorithm; no separate hash contract is introduced. Only
signature matches reach full-resolution comparison. Zero signature matches
leave the shadow unavailable, one exact full-resolution match is accepted, and
two or more exact matches remain ambiguous.

The final-pixel diagnostic defaults off. With it off, the reconstructed JPEG
bytes from `reconstruct_lossless_jpeg()` are returned unchanged as `.jpg` after
the structural and coefficient proof gates pass; `native_pixel_exact` remains
unchecked (`null`) and the final comparison timing is zero. With
`BOOKWALKER_FINAL_PIXEL_VERIFY=1` (also `true`, `yes`, or `on`), the browser
full-resolution comparison is performed and exactness is required. An invalid
explicit value fails fast. Spread output is all-or-none: one failed part makes
every part native PNG. Unsupported JPEG layouts, ambiguous mappings or
candidates, segment overflow, coefficient mismatch, dimension mismatch, and an
enabled browser comparison failure are all non-fatal native PNG fallbacks.
Active segments, completed mappings, and retained browser source references are
bounded and cleared after the capture window.
`BOOKWALKER_CAPTURE_MODE=canvas` bypasses original/native/lossless capture and
continues to use the rendered-canvas fallback.

For mutable purchased-viewer canvas sources, draw-time pixel snapshots are allowed, but PNG encoding occurs only after the selected draw calls are known.

The BookWalker `BOOKWALKER_CAPTURE_MODE=canvas` mode is retained as a diagnostic lower-level control and bypasses native/original capture.

### Manga ONE

Prefer the verified original/native WebP resource when it represents the page directly.

Use lower capture levels only when that direct resource path is unavailable or unsafe.

Site-specific details remain in each Adapter's documentation.

### Magapoke

The CDN JPEG is a scrambled transport image, not a completed page. Do not save
it directly or pixel-decode/JPEG-reencode it in the production Adapter. Prefer
the following verified hierarchy:

```text
scrambled transport JPEG
    -> observed drawImage mapping and JPEG structure validation
    -> quantized-DCT tile/block permutation
    -> lossless reconstructed JPEG
    -> native pixel tile reconstruction
    -> PNG
    -> canvas Locator screenshot PNG fallback
```

The coefficient level is production-enabled only with `jpeglib>=1,<2` and
only when all components are 1x1 sampled (grayscale or 4:4:4), all observed
source/destination rectangles are 8x8 aligned, and the existing base/final
draw safety checks pass. The mapping is calculated from each observed
`sx/sy/sw/sh/dx/dy/dw/dh`; no fixed tile count or permutation is assumed.
The implementation verifies dimensions, component sampling, quantization
tables, quantized coefficient arrays, DQT/DHT/DRI payloads, progressive mode,
source APPn/COM metadata presence, and untouched coded blocks at the right
edge. Any failure falls back to the existing PNG reconstruction and then the
Locator screenshot path. 4:2:2 and 4:2:0 remain rejected because equivalent
chroma upsampling at tile seams has not been proven.

Magapoke also has a bounded Adapter-level capture retry. In addition to the
existing two retries for source response body acquisition, the Adapter may
make two additional attempts for the current visible spread when rows,
mapping/base/final draw metadata, canvas dimensions, or source JPEG bytes are
transiently incomplete. Each attempt re-observes the whole spread and never
mixes provenance between canvases. Deterministic unsafe mapping and a
successful PNG reconstruction are not retried; after the bounded attempts the
existing PNG and Locator fallback levels remain authoritative.

Native reconstruction is accepted only for integer, equal-size rectangles with
identity transform, normal source-over composition, complete non-overlapping
coverage, and a uniquely attributable current-episode source. Unknown or
unsafe mapping, invalid/unavailable JPEG, decode failure, or incomplete
coverage falls back for the whole visible spread.

The diagnostic reference remains in `poc/magapoke_lossless_jpeg.py`; the
production implementation is in the Magapoke native capture helper and uses
the same observed mapping and restrictions. Other sampling factors are
rejected because chroma upsampling equivalence has not been proven.

The artificial fixture and five live artifacts from episode 244815 matched the
existing PNG reconstruction pixel-for-pixel and preserved quantized DCT
coefficients, quantization tables, and Huffman tables. The live JPEGs were
685x1024 grayscale with a 688x1024 coded grid; the two rightmost coded block
columns were left unchanged for the 13px visible edge plus padding.
`jpeglib.write_dct()` duplicates JFIF APP0 and may renumber component IDs, so
the validator treats JPEG container bytes as non-authoritative while requiring
the source metadata payloads and image coefficients needed by this path.
Lossless WebP is not used.

---

## 13. Provenance

The saved artifact's actual MIME type, extension, dimensions, and fingerprint remain authoritative.

It is useful for diagnostics to know whether a page came from:

```text
original
native
canvas
screenshot
```

A future manifest-level `capture_method` field may be added if it provides enough operational value, but this document does not change the current manifest schema by itself.

Do not infer provenance from the file extension alone.

---

## 14. Decision checklist for a new site

Before implementing capture, answer in order:

1. Can the exact visible page's original image bytes be identified safely?
   - yes -> preserve and save them as-is
2. Can the renderer source pixels and source rectangle be identified safely?
   - yes -> save native pixels, normally as PNG
3. Can the final content canvas be captured without viewer UI?
   - yes -> capture the stable rendered canvas/crop as PNG
4. Can a content Locator be isolated?
   - yes -> Locator screenshot
5. Otherwise:
   - viewport screenshot as the last resort

At every level also ask:

- Does this interfere with rendering or navigation?
- Is the mapping unambiguous?
- Are temporary resources bounded and cleaned up?
- Is spread order correct?
- Is there a safe lower-level fallback?

When in doubt, prefer the lower capture level that is demonstrably correct.
