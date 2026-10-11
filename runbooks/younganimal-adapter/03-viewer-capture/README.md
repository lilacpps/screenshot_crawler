# Phase 03 — Viewer / original-image-first Capture

Status: The capture proof gates, pure-translation handling, and final nested-CI geometry rule passed independent review. Attempt 9 verified both final-code profiles: 16/16 standard-target pages and 44/44 top-empty pages used native VP8L with decoded-RGBA agreement, Runner END, ZIP, isolated Catalog completion, and unchanged source fingerprints. The independent audit is `output/younganimal_experiment/phase04_batch_e2e_20261011/attempt-9/independent-final-audit.json`. The historical D-only result retains `PASS_WITH_STATUS_PROVENANCE_LIMIT`. Source attribution is sampled; no all-page original-byte claim is made.

## Current bounded evidence (2026-10-11)


- The direct-target metadata report is ignored at
  output/younganimal_experiment/phase03a_viewer_probe_20261011_direct_target.json.
  Its preceding fresh canonical /1 observation proved work
  aee4fa742b0fe, the target at global position 1, and exactly one row-local 無料
  label. The direct target route returned HTTP 200 and its embedded public row
  independently proved exact route, same work, unique row, and exact 無料.
- This direct attempt followed a separate earlier listing attempt that stopped
  on an automatic page fetch returning HTTP 429 with Retry-After 1 for another
  episode. The bounded wait and retry-after were honored before the direct probe.
  The direct report observed no relevant 403/429 stop. It did not save response
  bodies, HTML, or page images. The prior listing proof age field is invalid
  because the probe mixed monotonic time with file modification time; age is
  UNKNOWN.
- The reader had one each of #comici-viewer, #xCVSeekBar, and #xCVPages, with 22
  direct wrappers and public seek min=1,max=21,step=2. Slot 0 was the exact
  empty top-PR lead-in; slots 1–16 were a contiguous rendered body interval;
  slot 17 was CI; slots 18–19 were empty PR; slot 20 was Good; slot 21 was Last.
  The probe read public seek values 21,19,…,1. It used the public range input
  value plus input/change events after an ArrowLeft operation advanced more than
  the requested single step.
- The probe found 984×1329 body canvas bitmaps with 656×886 CSS rectangles.
  It collected RGBA SHA-256, layout, and bitmap metadata at the seek positions.
  Its same_candidate_identity result only compared slot/canvas indices and
  attributes; it did not prove actual JavaScript object identity or write
  generation. The production capture uses actual in-page wrapper/canvas
  references, write/generation counters, and before/after pixel checks.
- At seek 1 the report observed #xCVLastPage visible at physical slot 21 and no
  body canvas selected. Its diagnostic flags body_continuity_proven and
  end_semantics_proven are false because that script did not assert those
  contracts. Production therefore independently requires exact role mapping,
  all body slots captured in order, minimum seek, the visible Last marker, and
  no body wrapper centered in view before END.
- The probe's resource summary includes image responses from
  viewer.younganimal.com, cdn-public.comici.jp, and api-ai.comici.jp, but there
  is no page-to-response or tile-to-page attribution. The api-ai.comici.jp
  responses are treated as tracking/pixel traffic and are excluded from the
  AccessGuard relevant-host profile. A prior draw snapshot saw
  960×1297 WebP source frames, 960×1296 intermediate tiles, and 984×1329 display
  canvases. It does not prove exact original bytes, complete tile reconstruction,
  JPEG identity, or source-native pixel provenance.

## Bounded source attribution and D-path live audit (2026-10-11)

- Reports are ignored under `output/younganimal_experiment/native_attribution_probe_20261011_retry2.json`
  and `native_attribution_validation_20261011.json`. Draw-time source snapshot,
  renderer replay, and selected target node/generation/write/layout/pixel proof
  were observed for sampled body slots 1, 8, 9, and 16. This validates only the
  sampled draws and does not attribute every response to every page.
- For sampled first/middle sources, the actual response bytes were WebP at
  960×1297. The viewer tiled each into sixteen 240×324 pieces on a 960×1296
  intermediate canvas and scaled that canvas to the 984×1329 body canvas. The
  map is nonidentity and decoded source bytes do not equal the final body pixels,
  so those sampled responses cannot be saved as-is. They are WebP, so JPEG DCT
  recovery is inapplicable to those samples. Slot 16 response-byte attribution
  remains UNKNOWN; no all-page original-byte claim is made.
- The D-path standard Runner report is under
  `output/younganimal_experiment/crawl_runner_20261011_handoff/`. Its 16 PNGs
  were ordered across body slots 1–16 and reached END. The manifest/ZIP audit
  verified raw SHA-256, CRC, PNG decode and 984×1329 dimensions. An independent
  audit matched every decoded RGBA SHA-256 to the prior direct probe's same-slot
  digest. First/middle/last were visually spot-checked, not all pages. Its
  restored completion status has a provenance limitation.

## Implemented local contract

The live sample has 22 wrappers and 16 body slots; that observed count is not a
fixed production constant. The adapter validates the exact lead and five exact
tail roles, derives the contiguous body interval between them, validates the
public seek against the physical wrapper structure, and freezes that mapping,
layout variant, and seek bounds through capture and END. A different physical
count is accepted only when it satisfies the same strict structural contract;
other wrapper totals for the standard profile have not been individually
verified live. A separately observed top-empty
sample had the exact `mode-has-top-emptypage` root flag and 51 wrappers: lead
slot 0, centered no-canvas blank slot 1 at max seek 51, body slots 2-45, and tail
CI 46 / PR 47-48 / Good 49 / Last 50. The implementation does not allowlist
51; it derives the contiguous body from the exact lead, blank, and tail roles and
requires `min=1`, `step=2`, and `max=wrapper_count`. Other wrapper totals for
the top-empty profile have not been individually verified live. The exact
blank is skipped with one public step to `max - step`, after which the first two
body slots must both be ready.
No generic blank skip is used. This does not borrow Hanayume dimensions or
total-5 arithmetic. Unknown roles, gaps, missing halves, route changes, and
inconsistent states fail closed.

The top-empty slot 1 is a structurally identified initial blank, not a body page; the adapter skips it only under the dynamic top-empty structural profile and requires the next two body slots ready. Other known initial blank/loading body classes remain structural states only, never proof of readiness. Unknown wrapper variants fail closed.

On initialization, the adapter validates a canonical configured work listing,
the exact free row in its selected numeric range, and the embedded episode row
before observing the viewer. A resumed public seek rewinds through the public
range control. Before initial capture, read-only observer metadata must show the
viewer navigation panel closed and the `.-cv-splash` count zero; the existing
one-second stable canvas/capture-epoch quiet proof
must then complete within the same five-second deadline. Reappearing UI resets
quiet time. Missing/malformed metadata and non-settling UI fail closed before
native or rendered collection. Capture stability uses a separate epoch; the
raw global DOM generation still advances for every observed mutation and stays
in diagnostics. Subsequent turns use public seek input/change
events and have finite observation deadlines.

D rendered capture reads PNG data URLs from the currently active body canvas in one
synchronous page evaluation. It retains actual DOM object references across the
read, then verifies exact route and seek, role mapping, node identity, dimensions,
canvas generation/write counters, layout, viewport, and pixel fingerprint.
Python decodes the PNG, verifies size and format, and compares the decoded RGBA
fingerprint to the synchronous canvas readback. The generic screenshot fallback
is disabled. This is rendered-canvas PNG output; it is not original-byte capture.

The rendered-path Runner fixture starts from resumed seek 11, captures the 16 ordered physical body slots as PNGs, validates the manifest source URL and page sequence, and packages a ZIP. The synthetic top-empty fixture models 51 wrappers and 44 body slots, starts blank at seek 51, steps to 49, and now captures all 44 pages as native VP8L through strict END and ZIP. It compares every decoded output RGBA to independently read fixture source-canvas pixels. The fixture delays navigation/splash teardown beyond the old quiet threshold, reopens the UI during settling, and proves that native selection/encoding wait for final teardown plus one full quiet interval. It remains synthetic evidence, not a live 44-page result. The C native path separately snapshots a full-frame
source canvas at draw time using runtime source/target dimensions, copies it to
an immutable private canvas, and replays the same full-frame transform into a
scratch canvas. It selects native pixels only when replay RGBA exactly matches
the active rendered body canvas and the full strict Python viewer parser agrees
with the initialization-time mapping, layout variant, and seek bounds before
selection and after encoding. Context, clip, dimensions, generation,
write count, node identity, layout, and pixels are bound to a single-use proof.
Candidate/proof state is capped at one current spread; unsupported or missing
halves discard native state and use rendered PNG for the whole spread. Failed or
cancelled selection clears the bounded candidate/proof window even when Python
did not receive its token; successful cleanup releases only the selected slots
to preserve later draw-time snapshots. Once
native proof is selected, any post-encoding mutation fails closed without saving
the spread. VP8L WebP is used only after exact decoded-RGBA equality; otherwise
the verified source PNG is kept. A separate local access test verifies that an
unknown free label stops before episode navigation. A synthetic HTTP 429 test
verifies the range stop is fail-closed. A transient root navigation-class
add/remove after Python encoding still fails the capture-epoch proof
with unchanged selected node and RGBA pixels. These tests do not replace live
verification of the top-empty profile.

## Capture method decision tree

Use this evidence order and do not generalize beyond its proof:

A. Exact source bytes: only if the response/draw chain proves an exact one-page
   mapping to captured body content.
B. Lossless JPEG reconstruction: only if observed source format and complete
   source/destination tile map, MCU alignment, and coefficients prove reversibility.
C. Source-native pixels: implemented locally with immutable draw-time snapshots
   and full-frame pixel replay; attempt 9 passed both the 16-page standard and
   44-page top-empty direct Batch profiles with native VP8L output and exact
   RGBA agreement. Runtime dimensions are taken from each proven draw, not
   copied from Hanayume.
D. Rendered body-canvas PNG: verified live through the standard Runner and
   independent manifest/ZIP/hash audit for the exact target; it is the atomic
   fallback for an unsupported native spread.

Do not infer JPEG suitability from dimensions or from a WebP transport sample.
Do not store image bodies from research probes. Bounded source-native research
retains only sanitized route/dimension/format/hash/map metadata. Keep the D PNG
path available when C evidence is unsupported. Historical attempt results were:
attempt 5 failed on the top-empty profile; attempt 6 passed top-empty under the
preceding geometry rule but failed on the standard profile's last spread;
attempt 7 passed the provided standard profile but its top-empty navigation
timed out before capture; attempt 8 failed closed during top-empty native
verification. A separate diagnostic harness reported a NameError; that harness
error is not identified as the cause of attempt 8's production failure. Attempt
9 independently verified the final rule on both profiles.

## Tests / exit

The final affected Younganimal capture-unit and browser suite passed 84 tests,
0 skipped, with 5 existing pytest-asyncio deprecation warnings in 133.19s;
`ruff check src tests` passed. Full `pytest -q` was not run because the change
is site-local. The independent read-only CLI review inspected a SHA-snapshotted
code view and did not run tests. The current coverage includes a full 44-page
all-native top-empty Runner fixture, delayed/reappearing UI
settle checks, malformed/non-settling metadata failures, and post-encoding
transient root-class mutation coverage. Its affected test results and lint/compile
checks are recorded in the latest progress checkpoint. Coverage includes native synthetic Runner/ZIP,
whole-spread D fallback, same-value reset/redraw and replacement mutation
failures, known-but-unready initial blank, strict proof decoding, and lossless
WebP/PNG fallback, cancellation cleanup before token return, frozen mapping drift,
and independent source/renderer pixel comparisons for all 44 top-empty pages
plus ZIP-byte preservation. A browser test now also changes a standard middle
spread into a separately valid top-empty structure after `detect_state`; direct
parsing accepts the same active nodes and coordinates, while the frozen mapping
rejects capture before either collector or locator fallback. The valid-profile mapping drift regression had passed separately; its negative control with only the frozen comparison disabled failed as intended.

## Historical failure-diagnostics iteration (2026-10-11)

At that historical attempt-3 checkpoint, the top-empty 44-page direct Batch
failed closed at native postproof before saving pages. Its Runner harness
returned the static reason `native_reader_layout_changed` but discarded
expected/actual details, so the failed subcondition was unknown. The earlier
diagnostics-only change added
bounded expected/observed route, seek, DOM epoch, root-node identity, wrapper
count, active-slot, and viewport fields; per selected canvas it reports proof
and current generation/write values, dimensions, rectangles, readiness/context,
and full-pixel equality only when the exact selected target/wrapper/holder and
proof dimensions pass the existing pixel bound; otherwise readback fields are
null. Rectangle equality uses raw coordinates before output rounding. It
includes at most 64 sanitized mutation records since proof selection and marks
overflow or per-record summary failure as incomplete. Initial quiet metadata is
retained in Runner failure diagnostics. No capture gate changes were included in
that diagnostics-only iteration.

## Historical attempt-4 capture-epoch checkpoint (2026-10-11)

Top-empty attempt 4 failed before saving pages. Expected/actual details show
only global DOM generation changed 702 to 704, with selected nodes, canvas
generation/write values, dimensions, raw rectangles, readiness/context, and
pixel/replay proofs matching. The complete two-record journal places both
class changes on nonselected physical CI slot 46: one same-assignment and one
serialization change with unchanged allowlisted class flags. The local change
keeps the raw global epoch incrementing for all records and adds a distinct
capture epoch. Only a class mutation on the structurally identified CI wrapper
with exact `{-cv-page, mode-ci}` old and reconstructed new ASCII-whitespace
token sets is omitted from that epoch. All other mutations, unknown values,
non-ASCII whitespace, structural changes, and changed/restored classes count.
Candidate draw-to-collection validation is unchanged; native post-encode,
Python quiet, and rendered-D pre/post checks use the capture epoch while
retaining their full proofs. Synthetic tests cover all 44 native top-empty
pages, exact independent fixture-source RGBA and END/ZIP, accepted CI class
serialization changes, rejected mutations, and rendered-D pre/post behavior.
The affected capture unit and complete Younganimal browser Integration module
passed 74 tests, 0 skipped, with 5 existing pytest-asyncio deprecation
warnings. Targeted Ruff, compileall, and `git diff --check` passed.
This was the implementation hypothesis at that checkpoint. The attempt-5
records later showed `canonicalCiWrapper=false`; this wrapper-only
interpretation is withdrawn and superseded by the current widget evidence
below.

## Historical nested-CI widget implementation checkpoint (pre-final geometry rule, 2026-10-11)

Attempt 5's complete failure record shows a global DOM epoch change 682 to 684
and capture epoch 677 to 679 before any page save. Both records are associated
with nonselected CI slot 46, but `canonicalCiWrapper=false` and
`canonicalCiClassNoop=false`. A separate bounded probe observed a class
mutation on an offscreen `DIV.-cv-ci-content` with one exact structure:
immediate parent `DIV.-cv-ci.-cv-page-content`, directly under the canonical
CI wrapper. The class transition was base `{-cv-ci-content}` to the same set
plus `mode-scroll-bottom`. Associating that observation with the attempt-5
failure is an inference, not a same-run identity proof.

The local rule exempts only ordinary class mutations on that sole-child nested
CI widget when it and the CI wrapper are wholly offscreen, and the old/new
token sets are base-to-base, scroll-to-scroll, or base-to-scroll. Reverse
transitions, unknown tokens, namespaces, missing/reconstructed values, other
ancestors, IDs, structure, and all non-CI changes still advance capture epoch.
The raw global epoch still counts every observed record. Candidate
draw-to-collection eligibility and every mapping, node, generation/write,
layout, context, readiness, pixel, post-encode, and cleanup proof are
unchanged.

The 44-page synthetic top-empty Runner captures all pages as native VP8L, with
independent source-RGBA equality, END, and ZIP-byte equality. Its verified
widget mutation leaves capture epoch stable while the raw global epoch
advances. Unknown/reverse/lookalike/reparented/replaced/missing/namespaced
widget cases fail before save, locator fallback, or proof leak. The current
focused selection passed 29 tests, 0 skipped, with 5 existing pytest-asyncio
warnings; the full capture unit file passed 32 tests, 0 skipped, with 1
existing warning. Ruff, compileall, and `git diff --check` passed. These are
synthetic results; independent review is required before the next live Batch.
