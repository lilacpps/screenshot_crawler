# 03 — Free Viewer / Capture

Status: Phase 03 PASS, BLOCKING 0 (174 passed, 0 skipped). Phase 06-B PNG output and Phase 06-C coefficient findings are accepted historical checkpoints. Phase 06-D code review and independent live Tester both passed with BLOCKING 0; the standard two-product route verified 39 lossless WebP pages and Catalog artifacts. See [PROGRESS](../PROGRESS.md).
Explorer researches unknown variants; Implementer writes; Reviewer gates;
Tester independently checks tricky captures when needed.

## Objective and scope
Add piccoma/adapter.py and only justified site-local access or native_capture
helpers. Preserve common Core Runner, Browser Session, Capture Strategy,
manifest and packaging; no generic refactor without explicit Lead gate.

## Behavior
- Configure auto as safely direct-only (if accepted) and explicit direct;
  reject quota and quota resources. Validate Catalog external ID, target URL,
  live product/episode identity and **current genuinely free entitlement**
  prior to saving any body page. A stale Catalog free is insufficient.
- Never click a ticket, ¥0+, charge, pay, login, rental or unlock CTA;
  personal active access does not qualify as unconditional free. Wrong target,
  redirect, unsupported UI and access wall fail closed.
- Detect exact supported viewer types, start/rewind to the first body page
  with bounded verified controls if reading position persists. Avoid fixed
  sleeps as the only change signal; use stable page identity and readiness.
- Represent CONTENT, LOADING, AD, END, NEXT_CONTENT and UNKNOWN from
  observed page structure. Incomplete spreads remain loading/unknown; no
  single-half capture. END follows final body with explicit evidence,
  no implied auto-navigation into the next paid episode.
- Capture priority: exact original bytes with proven identity → attributable
  source-native pixels → rendered canvas → Locator screenshot. Preserve
  native JPEG/WebP/PNG. Treat scrambled/composited/encrypted resources as
  **not native** without a separately validated safe method; never bypass
  DRM or access controls. No lossy conversion as a fidelity improvement.
- Preserve max_pages, same-content, bounded retries, AccessGuard/pacing,
  progress and manifest contracts.

## Tests / acceptance
Unit tests for wrong target, stale free, forbidden clicks, state machine,
page identity, timeout, duplicate prevention, END, source-provenance checks.
Browser integration for first/last, rewind, lazy loading, horizontal/vertical
if supported, multi-page spread ordering, ads/unknown, wrong-next-content
and render fallback. Perform a live free episode crawl, checking each saved
page against visible content, image count, reading order and terminal state.

Gate: no silent missing/duplicate page, false END, non-free access or
unsound original-byte attribution. Reviewer zero BLOCKING. If no verified
free episode is available, mark live verification blocked, not passed.

## Phase 06-B historical PNG implementation evidence (2026-10-09)

The observed horizontal reader's complete one-image/408-tile JPEG draw graph
was replayed at that checkpoint in a detached canvas with exact fractional
coordinates and recorded supported context state. Its output was a
source-derived PNG after a separately proven solid-white alpha composite; the
tiled JPEG bytes themselves were not saved as a page. Live canvas readback
remains tainted. Native replay
requires exact unique response attribution, stable image-load and target
generations, bounded complete traces, supported operations, verified backdrop
(`background-clip:border-box`, `clip:auto`, no borders/radius), and successful
materialization. Per-target dimension observers also catch same-value attribute
resets while the canvas is detached; they are limited to current/candidate
canvases and disconnected on retirement. If pre-capture proof is unavailable, Core
`capture_locator` is used only while the active canvas generation stays
unchanged. A target mutation during either path fails closed. Unsupported
layouts, draw graphs, backdrop structures, and resources remain unsupported.

For products 28600/1910027 and 28606/2001009, production capture was checked at
p1/middle/last (p1/p12/p24 and p1/p8/p15 respectively). Each of the six native
replay PNGs was RGB pixel-identical to the unchanged clean Locator screenshot;
both traversals reached explicit END without leaving the requested viewer URL.
The historical Phase 06-B PNG checkpoint passed its independent Reviewer and Tester gates. Across the two exact-free seeds, that standard route verified all 39 pages, ZIP/Manifest membership, CRC and image hashes, Catalog completion/artifacts, explicit END, and no quota/resource mutation. The pre-final-compatibility full suite reported 1881 passed, 3558 warnings, and 0 skipped; the final NamedNodeMap compatibility regression passed separately (1 passed, 48 deselected, 0 skipped). Phase 06-D WebP live results are recorded below.

## Phase 06-C exact JPEG coefficient feasibility probe (2026-10-09)

The bounded probe rechecked exact-free listing status and composite identity, then examined only p1 for 28600/1910027 and 28606/2001009. Each had one exact observed JPEG response and a complete 408-draw production trace. The response bodies were 1,951,370 and 789,375 bytes; `jpeglib.read_dct` succeeded, and the temporary files were deleted. The probe used no next-page or entitlement action and closed its owned Pages and CDP session. Independent evidence/design review: PASS, BLOCKING 0. Sanitized evidence is at ignored `output/piccoma_experiment/source_capture_research/phase06c_jpeglib_p1_evidence.json`.

Both observed images are baseline 8-bit, three-component 4:4:4 JPEGs with 8x8 MCUs. The actual trace has 50-pixel destination tiles, 44/42-pixel edge widths, source-height `50.01`, destination-height `50`, and image smoothing enabled at quality `low`. Passing the unmodified exact rectangles (without rounding) to Jump+ `dct_lossless_feasibility` returned `tile_geometry_not_mcu_aligned` for both. Existing Jump+/Magapoke coefficient permutation requires integer, equal-size, MCU-aligned rectangles, so that method is unsupported for this observed graph. This finding is limited to the existing method and does not claim that every custom JPEG transform is impossible. Equal-50-height seam/phase and 4x4 grouping calculations in the report are diagnostic only; they are not production geometry or a rounding rule. At the Phase 06-C checkpoint, production remained the verified source-derived/composited PNG path; Phase 06-D subsequently adds lossless WebP encoding without changing replay geometry. The isolated research script passed `py_compile` and Ruff; no implementation/test changes or full-suite run were made for this probe.

## Phase 06-D lossless WebP output

The approved native replay workflow is unchanged through exact JPEG response
attribution, complete fractional tile replay, and verified-white RGB
composition. The adapter uses Pillow WebP `lossless=True, method=6` and accepts
only a single VP8L chunk with exact RIFF/chunk lengths and matching encoded
dimensions. It fully decodes the output and compares every RGB byte with the
verified composited pixels. Invalid, truncated, animated, or lossy WebP cannot
be reported as the native lossless method. If WebP encoding or round-trip proof
fails, the same verified native pixels remain PNG with an
`encoding_fallback_reason`; if source provenance was unavailable, Core capture
remains PNG. Core capture rejects WebP under PNG method metadata. Active target
generation is checked after encoding, and mutation still fails closed.

Focused local verification passed 99 Piccoma native-capture unit/browser tests
and 26 packaging tests, with 0 skipped; `ruff check src tests` and
`git diff --check` passed. The code Reviewer and independent live Tester both
passed with BLOCKING 0. The Tester completed full Discovery (432 and 218 rows),
incremental known-streak checks, and a plan of 444 direct candidates, 206
skipped non-free candidates, and zero quota candidates. Standard Batch,
Runner, Manifest, packager, and Catalog produced 24 WebP pages at 844x1200 and
15 at 842x1200. All 39 were validated single-VP8L outputs without fallback;
page IDs and hashes were unique and ordered, ZIP members matched the Manifest,
and CRC/hash, completed Item, succeeded END Run, and present Artifact checks
passed. Six current Core RGB comparisons had zero changed pixels and all six
were visually inspected. Source/free rights state remained unchanged and
resource rows remained 0 before and after. The full suite was not rerun after the final site-local changes.
The earlier 1881 passed, 3558 warnings, 0 skipped full-suite result came from the reviewed
checkpoint immediately before the final NamedNodeMap compatibility fix. That fix was tested
separately, and the suite was not rerun afterward. Downstream WebP reader compatibility outside
the tested browser/Pillow/ZIP path is unverified. The supported layout remains horizontal at
1904x1200/DPR 1; other draw/backdrop/resource variants remain unsupported.
