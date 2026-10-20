# Yanmaga source-native-pixel capture research

This record summarizes bounded normal-viewer probes of one positively
classified free episode in the designated work and the resulting source-native
pixel capture. It contains no page images, raw network URLs, signed values,
cookies, or response bodies. The detailed probe material is private and ignored
under `output/yanmaga_experiment/native-original-probe-20261020/` and the
current implementation run under `output/yanmaga_experiment/native-live-full-webp-20261020/`.

## Observed pipeline

- The first-party viewer bundle's active image-loader path draws tile images
  into canvas segments, then calls `HTMLCanvasElement.toDataURL` with
  `image/jpeg` and quality `0.9`, constructs JPEG Blobs, and creates object
  URLs for the body `<img>` elements.
- During an ordinary Chapter 1 load, the three body images in the first
  logical page had `blob:` current sources. Their JPEG bytes matched the
  corresponding canvas `toDataURL` payload byte-for-byte. The three segments
  were 1127×536, 1127×536, and 1127×538. This establishes that the displayed
  blobs are viewer-generated JPEGs, rather than unchanged source responses.
- The bounded 36-page normal traversal retained all 108 segment responses.
  Every page had the same ordered 1127×536, 1127×536, 1127×538 dimensions;
  these are JPEG output dimensions, not evidence that any segment is a whole
  page.
- The matching upstream image response was a 1189×1664 JPEG. Visual
  inspection showed a shuffled tile atlas, not a complete readable page. The
  first-party page metadata described each logical page as 1125×1600 and
  exposed 36 ordered primary page identifiers.
- The normal viewer issued 30, 40, and 50 `drawImage` calls for the three
  first-page canvases. The draws used multiple source and destination
  rectangles from the atlas. Therefore neither the atlas nor an individual
  segment is an exact original-page image, and the JPEG segment bytes already
  include lossy encoding.
- At the measured 2560×1800 viewport, the logical page wrapper was
  1265.625×1800 CSS px (1.125 scale). The three segment image tops were 0,
  598.5, and 1197 CSS px, corresponding to native offsets 0, 532, and 1064.
  Images overlap by four native rows; the last extends two native rows below
  the 1600-pixel page. The segment width extends beyond the logical 1125-pixel
  page and is clipped by the page wrapper. Correct composition must follow
  native DOM sibling paint order and clip to the logical page bounds; simply
  stacking full segment images would be wrong.

## Capture decision

No exact complete upstream page image was observed. The best supported path is
to copy each viewer canvas's RGBA pixels immediately before its original JPEG
encoding, bind that copy to the resulting body Blob only through unique exact
JPEG-byte equality, then replay the three verified segment pixel arrays at
their measured native positions and DOM painter order into a 1125×1600 page.
Encode that reconstructed native-pixel page as lossless WebP and verify exact
decoded RGBA equality before returning `image/webp` / `.webp`.

This output must be described as reconstructed pre-JPEG viewer pixels, not
original source bytes. A group is eligible only when all three segment sources
are uniquely bound, stable, and the observed page geometry/style contract is
met. Ambiguous byte matches, missing segments, overflow, unsupported
compositing/style, or changed sources fail closed to the existing rendered
PNG path for the whole logical page group. No access, entitlement, or reader
navigation behavior is changed.

## Evidence and limits

Sanitized summaries are in the ignored probe directory:

- `live-link/trace-summary.json`: segment Blob metadata and canvas draw
  observations.
- `live-link/summary.json`: first-page wrapper and segment geometry, image
  dimensions, and safe source shapes.
- `live-link/source-map.json`: first-party page metadata and source-response
  correspondence using sanitized URL shapes.
- `first_party_scripts/`: the observed first-party minified bundle, retained
  privately for source inspection.

The source-response mapping in the probe used a resolved-path-suffix
correlation; it did not rely on display dimensions alone. The live observation
covers this work, episode, viewer layout, and browser profile only. Other
reader layouts are not supported by this evidence. Runtime proof must still
reject non-normal transforms, filters, opacity, blend modes, or unverified
clipping/paint behavior. Pixel buffers, matching bytes, and asynchronous
verification must be tightly bounded; overflow or non-unique association must
not silently select a candidate.

## N2 implementation and live verification

The helper runs only on the top-level Yanmaga viewer route. It observes the
viewer’s existing `toDataURL("image/jpeg", 0.9)` call without changing its
arguments, return value, exception, or navigation behavior. Before that
encoding, it makes a bounded copy of the opaque sRGB/unorm8 canvas pixels. The
resulting JPEG bytes are associated to the Blob and current body-image source
only by exact byte equality, with ambiguity rejected rather than selecting the
latest candidate. Pending captures, retained evidence, pixel area, and encoded
bytes are bounded, and owned hooks/references are disposed on adapter-owned
cleanup paths.

The verified runtime DOM is one `#content-pN` wrapper containing one `.pt-img`,
three absolute overflow-hidden segment hosts, and one image in each host. The
native first-party page metadata/logical `.pt-img` box is 1125×1600. The three
segments are 1127×536, 1127×536, and 1127×538 at native Y offsets 0, 532, and
1064. Their four-row overlap and final two-row overrun are clipped in DOM paint
order to the logical page. The outer wrapper accepts only the observed pure X
translation and 0/2 CSS px right gutter. The measured host `::after` is admitted
only by an exact no-paint style predicate. Full page/host/image/source/style
proofs are rechecked atomically across the spread before accepting an output.
Missing/duplicate/mutated sources, unsupported geometry or paint, alpha, budget,
or codec proof failure demotes the whole visible group to the existing rendered
locator PNG. A supported page encodes as one lossless `VP8L` WebP and must decode
to exactly the composed RGBA pixels; metadata identifies reconstructed native
pixels and explicitly says original source bytes were not used.

The fresh shared-CDP `CrawlerRunner` run in
`output/yanmaga_experiment/native-live-full-webp-20261020/` completed the
red-free Chapter 1 to positive END with 36 ordered body pages and 36 Manifest
entries/files. All 36 used `native_pre_jpeg_lossless_webp`; there were no
fallbacks. An independent offline audit confirmed 36 unique hashes matching
Manifest fingerprints, successful single-VP8L decodes, fully opaque pixels,
and 34,377,750 total payload bytes. Pages 1, 18, and 36 were visually compared
against the prior rendered-PNG controls for body coverage, order, crop, and no
reader UI/ad/rental overlay. That is a visual/layout comparison, not pixel
identity against the PNGs. The WebP encoder separately enforces exact RGBA
round-trip equality. No ticket, point, quota, grant, signup, or next-episode
action occurred. The initial Chapter 11 ZIP audit verifies the historical PNG
path. The later normal Chapter 11 WebP Batch/ZIP E2E and independent pixel equality against separate RGBA reference pages are recorded below.

## N4 bounded raw-pixel retention

An earlier ordinary Chapter 11 initialization hit the 96 MiB raw-pixel cap
before its first capture. Its isolated direct-Runner snapshot held 41 exact
canvas-to-Blob candidates and 99,185,016 RGBA bytes; the next segment would
have raised that counter to 101,601,304 bytes, exceeding the old 100,663,296
byte cap. A separate fresh ordinary CLI diagnostic with a one-page maximum
observed 21 exact-bound candidates and 50,805,160 raw bytes immediately before
its first capture, with 5,807,040 encoded characters, zero in-flight reads,
and no ambiguity, miss, read failure, or overflow. It saved page 1 as native
1125×1600 WebP. After page-1 release the raw-pixel counter was 43,547,280
bytes, exactly one page (7,257,880 bytes) lower. The CLI intentionally stopped
at `max_pages=1` (exit 1); that diagnostic did not reach END, ZIP, Artifact, or
Completed. Its observer projection did not establish page IDs for all other
retained candidates, so none are inferred.

The implementation now has a fixed 256 MiB (`268,435,456` byte) raw-pixel
retention cap in both the Python and browser observer. The cap is not a
preallocation and does not represent all JavaScript heap or Chrome RSS. The
other finite limits remain 192 total candidates, 48 pending candidates/tasks,
32 MiB encoded payload characters, 192 URL bindings, and 1 MiB per segment.
No compression was added inside viewer hooks and no pacing or shared Core
behavior changed. The size covers the known 36-page layout's 108 source
segments: `36 × 7,257,880 = 261,283,680` bytes (about 249.2 MiB), below the cap
with about 6.8 MiB remaining. This is a bound for the observed layout, not a
general cache or whole-process memory claim.

The browser-backed eager-preload regression binds 60 exact JPEG/Blob candidates
before the first capture, retains exactly 145,157,600 raw bytes, then captures
the first page as lossless WebP and confirms that releasing it subtracts
7,257,880 bytes. A separate boundary regression accepts a candidate exactly at
the configured limit and rejects the next candidate without allocating an
additional pixel copy. The current Yanmaga Unit plus browser Integration
selection passed 76 tests, 0 skipped, with 23 existing pytest-asyncio/Python
3.14 deprecation warnings. Full `ruff check src tests` passed. The independent
Reviewer accepted the N4 cap change with BLOCKING 0.
The normal Chapter 11 WebP Batch/ZIP E2E and independent all-20-page RGBA reference comparison passed. The daily-free notice applicability to red-free rows remains unknown; other reader layouts are unsupported, and a complete original full-page server response was not observed in these probes.

## Existing adapter references checked for the Yanmaga capture design

The implementation was compared with existing site-local capture patterns;
their helpers were not imported or copied. `younganimal/native_capture.py`
`encode_native_webp()` provides the relevant output invariant: one lossless
VP8L WebP, validated dimensions/frame structure, and exact decoded RGBA
round-trip. Yanmaga uses that validation objective around its separately
proven composed viewer pixels. `piccoma/native_capture.py`
`capture_native_tile_replay()` is appropriate when a complete source/destination
tile draw trace proves replay; that replay was not substituted for Yanmaga's
observed first-party composition of three overlapping segments.
`kadocomi/native_capture.py` demonstrates bounded `createObjectURL` Blob and
canvas-source provenance; Yanmaga instead associates its pre-JPEG canvas copy
to a displayed segment through exact JPEG-encode-to-Blob byte binding.
`mangaone/native_capture.py` `capture_source_bytes()` preserves complete
viewer Blob bytes when those bytes are already a whole WebP or PNG image, and
`comicfuz/native_capture.py` `capture_comicfuz_source_bytes()` accepts a
validated complete JPEG matching the selected image dimensions. Yanmaga's
observed upstream JPEG was a shuffled tile atlas and its viewer Blob was a
re-encoded segment, not a complete page; those direct-byte preservation paths
do not match this evidence. No source-adapter helper is shared across sites.

## Chapter 11 normal Batch/ZIP verification

The fresh ordinary CLI run is isolated at
`output/yanmaga_experiment/nv-e2e3/q/primary/`. Full Discovery returned 13
rows, incremental returned five known rows, and the first plan had five
`free/direct` candidates, eight `unknown` skips, and quota zero. Normal Planner
order selected Item/Source 2, Chapter 11. `batch run --limit 1` succeeded with
20 pages and positive END. All 20 Manifest pages used native 1125x1600
single-VP8L lossless WebP with unique payload hashes and no fallback. The
ordered ZIP passed CRC and all Manifest hash checks; Tester and Root
independently audited the archive. The archive is 18,830,115 bytes with
SHA-256 `8d32c1ba953e2093e4c42945ce8bd1c2ff940884d2c343f6b68dc5ba6d4232b5`.
The Manifest snapshot SHA-256 is
`e4d0bdec2c96606023a10c085dd100d8c952b5a598f9e6343f50ea7da2d68daa`.
Artifact is present and Item 2 is completed. Repeated full/incremental
Discovery preserved IDs, positions, completion time, and Artifact; the final
plan had four direct candidates, eight unknown skips, and one completed skip.
Tester visually checked first/middle/last body pages; Root's all-page contact
sheet and archive review found body pages without UI or terminal-card
contamination.

The independent reference control completed all 20 pages / 60 source segments with no overflow, send failures, or scan errors. Pillow composites of the reference segments match decoded pixels in the successful normal-CLI ZIP exactly on all 20 pages. Root's independent audit is `output/yanmaga_experiment/nv-e2e3/q/primary/root-independent-pixel-equality.json`. The earlier zero-snapshot attempt was a QA observer initialization issue: its observer ran before `document.documentElement` existed. The QA-only observer now observes `document` and performs an initial scan; a four-contender local lock fixture also passed. These QA harness fixes do not alter production capture. Earlier rendered-PNG outputs are historical controls and are not the current output format.
