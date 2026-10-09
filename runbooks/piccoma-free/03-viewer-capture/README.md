# 03 — Free Viewer / Capture

Status: Phase 03 PASS, BLOCKING 0 (174 passed, 0 skipped). Phase 06-B source-derived PNG implementation, final independent review (PASS, BLOCKING 0), and independent Tester E2E are complete. The full suite passed on the checkpoint immediately before the final NamedNodeMap compatibility fix; that fix has its own passing focused browser test and Reviewer pass. Live evidence and current capture scope: [PROGRESS](../PROGRESS.md).
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

## Phase 06-B implementation evidence (2026-10-09)

The observed horizontal reader's complete one-image/408-tile JPEG draw graph is
now replayed in a detached canvas with exact fractional coordinates and
recorded supported context state. The output is a source-derived PNG after a
separately proven solid-white alpha composite; the tiled JPEG bytes themselves
are not saved as a page. Live canvas readback remains tainted. Native replay
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
Final independent Reviewer gate: PASS, BLOCKING 0. Independent Tester final live E2E: PASS. Across the two exact-free seeds, the standard route verified all 39 pages, ZIP/Manifest membership, CRC and image hashes, Catalog completion/artifacts, explicit END, and no quota/resource mutation. The pre-final-compatibility full suite reported 1881 passed, 3558 warnings, and 0 skipped; the final NamedNodeMap compatibility regression passed separately (1 passed, 48 deselected, 0 skipped).
