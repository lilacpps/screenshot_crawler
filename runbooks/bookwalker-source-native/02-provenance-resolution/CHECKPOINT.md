# Stage 02 checkpoint — 2026-10-08

Status: **COMPLETE**. Authority is [README.md](README.md).

This checkpoint preserves the useful evidence from the earlier heavier workflow while
making clear that Reviewer/Critic are no longer required for ordinary research.

## Current Lead decision

Required bounded live verification is complete after the user logged in again.
Final production Reviewer confirmed PASS with no remaining BLOCKING, including
the live evidence, current cover fallback controls and synchronized documents.
Stage 02 is complete with the explicit D boundaries below. No production
code changed during this continuation. Local validation remains 180 targeted
BookWalker tests and 46 browser-backed Integration tests, with Ruff/diff checks
passing. No credentials were submitted during the successful continuation.

| Investigated case | Classification | Accepted current evidence / boundary |
| --- | --- | --- |
| Manga body `9/159`, `11/159` | B | Two 844x1200 reconstructed JPEG parts per spread from 848x1200 coded sources; unique exact candidate, complete coded MCU bijection, coefficient/qtable/selector equality and mandatory native comparison at zero differing pixels for every part |
| LN `3/314`, `4/314` | B | 2048x1456 coded source to 2048x1453 JPEG; complete 2,944-tile mapping, unique exact candidate, unchanged coefficients/quantization/selectors and native pixel equality |
| LN `2/314` | D | Stable native PNG fallback at 722x1024; selected mapping ID exists but its usable upstream tile/source proof is unavailable (zero retained tile rows/dimensions/source identity). Historical 1448x2048 exact JPEG/bitmap evidence is not joined to this output |
| LN ordinary text `8/314`, `10/314` | A | Existing equal-size reconstructed JPEG path remains correct at 960x1280, with 1,200-tile proofs and unique exact input per part; optional old-path final-pixel comparison remains off |
| Manga cover, current run | D; historical A retained | Current native adapter selection returns no artifact, with zero original-match attempts/candidates. Actual Core rendered-canvas PNG fallback was captured at 1386x983; no current original-JPEG success or source-PNG claim |
| LN cover, current run | D; historical A retained | Current native PNG fallback at 722x1024; the historical full-resolution original-JPEG control was not reproduced, so it is not claimed as a fresh A pass |

No source-PNG authority (C) was established. Historical cover A observations
remain valid for their original windows; current unavailable original/native
selection is a separate fail-closed observation, not proof of a PNG source.
The existing original-JPEG path and its priority were not changed. The cover
control verifies actual fallback output, while original-JPEG regression remains
covered by the passing Unit/Integration suites and historical live evidence.
Zero original-match counters on a path with no native selection are unattempted
matcher diagnostics, not proof that the raw response pool contains no JPEGs.
Current cover provenance remains D; no underlying source-format change is inferred.

The recovery cause is direct, safe, completed tile mapping with separate coded
S and visible V dimensions, not a content label or page number. The raw exact
JPEG is a scrambled recovery input. Reordered coefficients plus rightmost four
columns (manga) or bottom three rows (LN) of visible-frame clipping reproduce
the selected native snapshot exactly. Source/destination mapping is MCU-aligned
and bijective across the entire coded frame, including hidden edge blocks.
New cropped output always requires available, dimension-equal intrinsic browser
pixel comparison even when the optional older-path flag is off. Rotation is
not inferred from dimensions; unsafe state and unsupported lineage fail closed.

Additional research is no longer warranted for this stage. Two representative
manga body spreads, two changed LN opening pages, one unsupported opening and
two ordinary-text controls cover the bounded contract. LN2 and current covers
would require a different retained upstream/selection proof, not a looser
size/filename/timing/similarity rule. Expanding into cached-canvas/no-clear or
cropped one-hop recovery is outside this proven direct contract. Full viewer
reverse engineering and all-seven-spread sampling are unnecessary. LN `5/314`
through `7/314` were not captured as new samples and retain their historical
D status; traversal is not capture evidence. Manga 2 was unused because no
specific cross-title hypothesis needed confirmation.

Research used Lead + Worker. Critic was invoked once for the material risk of
the partial-MCU contract and accepted its explicit S/V/full-coverage/mandatory
pixel gates. Production Reviewer required one real-Canvas nonuniform,
nonidentity 40x40-to-37x36 crop case; Worker added it and Reviewer confirmed
no remaining code/test/doc BLOCKING. Final live-evidence review was the last
completion gate and passed with no remaining BLOCKING; this was not a routine
research review. No additional broad research is required.

The active branch remains `research/bookwalker-source-native-20261005`.
Before the successful continuation, Lead fetched `origin` and merged current
`origin/main` `96fd5fff84567a4e2c644978d2b4c297174fa2ca` (already up to date),
preserving pending changes and unrelated `debug.log`. This is baseline sync,
not provenance evidence. The earlier CDP/login access failures were resolved
by the user's Chrome restart and subsequent intended-account login. Existing
user tabs and remote Chrome were preserved; only Worker drove the viewer.

## Final bounded live evidence (2026-10-08)

Each independent probe verified actual counters, explicitly returned to its
anchor as necessary, and verified page 1 before closing its dedicated Page.
Mapping/source IDs are window-local; repeated IDs across files are not joins.

| Case | Actual start / verified anchor / target / final position |
| --- | --- |
| Manga `9/159` | 7 -> 1 -> predecessor 7 -> 9 -> 1 |
| Manga `11/159` | 7 -> 1 -> predecessor 9 -> 11 -> 1 |
| Manga cover | 5 -> 3 -> 1; render-ready/capture/end all at 1 |
| LN `3/314` | probe entry 1 -> 2 -> 3 -> 1 |
| LN `4/314` | 2 -> 1 -> predecessor 3 -> 4 -> 1 |
| LN `2/314` stable fallback | 3 -> 1 -> 2 -> 1 |
| LN cover | 6 -> 1 -> capture/end 1 |
| LN `8/314` | probe entry 1 -> observed pages 2 through 7 -> 8 -> 1 |
| LN `10/314` | 4 -> 1 -> predecessor 8 -> 10 -> 1 |

The first combined helper overshot requested manga 9 and LN10 because an
arithmetic predecessor ignored spread counters. Those error cases are excluded;
exact counter-verified replacement probes establish manga9/11 and LN10. Only
successful LN3 and LN8 entries in that combined report are accepted. Its early
cover/LN2 records are superseded by stable controls with distinct hashes. The
LN10 helper originally had a copied manga label; Worker confirmed its requested
LN URL and corrected the filename/title, rather than inferring title from 314
or dimensions. A debug default `native_png` with zero captures is never PNG
success: manga cover acceptance uses actual Core fallback bytes instead.

| Ignored local metadata | SHA-256 |
| --- | --- |
| `output/stage02-manga9-exact-acceptance-20261008.json` | `cadc7dd4df15f5db87243b2a124aefa0ca96c7155eebc3b2cbfe0013c2693767` |
| `output/stage02-manga11-exact-acceptance-20261008.json` | `d3208c9d97d18ce9a1b6328474345f0e5e95250c41fce6f9dc947cdb98763993` |
| `output/stage02-ln4-stable-20261008.json` | `a8b64b2cafa5bdcb560c720df7edc75f9451a3d5660979b1a45901d49eef8826` |
| `output/stage02-ln10-exact-acceptance-20261008.json` | `780e740ec8728080e461cfcc644811be794c718b97d3c8fc19b0346c6f3a8d0c` |
| `output/stage02-stable-cover-ln2-20261008.json` | `7680c9f05537e4f4960156d2e05eb9874487b0f520fe1f3300791864c74e072f` |
| `output/stage02-manga-cover-fresh-control-20261008.json` | `db9c78f9fdcffda117eaa3711c58fddf25e7badbfd79955fba466d72868077c2` |
| `output/stage02-live-acceptance-20261008.json` (LN3/LN8 entries only) | `4f87fee1d55bb9a518ab5c08caf08a6d2894110147c5c8f66b4013c4c517052b` |

Manga9 output hashes match the earlier production proof below. Manga11 outputs
(right-to-left) are `317f6050ba53d017e42c8459c8c266aa044e7c8bb8e09b11988aaa610e0265b8`
and `347db891d426716d11659d7bde298cf2a72c8ae9f1855709eab9fafe7109166a`.
LN3 output is `99021c156581961ed0d9c1b70babd575d0f98e50ac4c8a8d326a4b778cf61496`;
LN4 is `180a062387ab818e9a61ba4bf4fd0be0b86f372a02cd255e339a08244b0e49e9`.
Actual rendered manga-cover PNG is `40221421b46e8cd041c4f97d3159286de12fd0b6d841d5c18371e9f747a64ae9`.
The stable LN cover and LN2 native PNG hashes differ, respectively
`b3a388bf46c2aee65291d7f568f4677033afdbd74cc8ebfcf74db3b3c5c5d3ef`
and `ec4a1483b90ed5e51a76bcfdfec3f584afda3f37239976d08c0bb6dd9f6034b5`.
Image bytes remain ignored; none is a committed fixture. Full-book/END live
runs were not required for this local capture contract.

## Baseline synchronization completed (not research evidence)

- Continued on `research/bookwalker-source-native-20261005` in the existing worktree.
- Initial local HEAD: `0209a8791a3d2bc7b11b0bff8018a7c039a24b8c`.
- Fetched `origin`; current `origin/main` was
  `96fd5fff84567a4e2c644978d2b4c297174fa2ca`.
- Merged that main baseline, then preserved the remote research branch's preflight
  documentation through `7d199d6`. Resulting baseline HEAD:
  `ef956698f92d30441a71be785b6bb5ac874011a5`.
- Both merges completed without conflicts. Stage 02 README/checkpoint and the
  BookWalker note remained present. Main's packaging/status documentation was
  retained; no BookWalker production Python change arrived through these merges.
- The unrelated untracked `debug.log` was left untouched; its before/after SHA-256
  was `13195f4a9302dee588b1705b9d691d4d1999b91505cfecedc70196edbc3db489`.

These SHAs record this execution, not a pinned main requirement for a future run.

## Initial post-login continuation — manga findings (superseded below)

The user corrected the login state and requested resumption. A new fetch found
the same current `origin/main`; merging it again reported already up to date.
The existing branch and unrelated `debug.log` were preserved. The access block
below is historical and no longer prevents the bounded research.

Manga R6 observed only `9/159` as the ordinary-body sample: actual entry/anchor
`1/159`, navigation `1 -> 3 -> 5 -> 7 -> 9`, observation start/end `9/159`,
and verified restoration to `1/159`. It recorded two 844x1200 native canvas
sources and full-frame, identity-transform renderer draws scaled to 998x1416.
Its dimension-ranked 848x1200 JPEGs were **not** candidate attribution evidence.
The legacy transform helper discarded its initial trace after initialization;
its empty trace and `PART_MAPPING_AMBIGUOUS` are collector limitations, not a
proven site ambiguity. R6's earlier cover-only attempt is excluded from body
evidence and is not a fresh cover regression.

R7 repeated the same spread with the corrected lifecycle: verify `1/159`, arm
native capture before the final `7/159 -> 9/159` turn, snapshot before any
trace-clearing capture/comparison, then restore and verify `1/159`.

- The production trace contained 4,133 observed operations; exact compact fetch
  returned both requested mapping IDs, with zero missing mappings.
- Renderer canvas 3 drew source canvas 6 at 844x1200 through exact completed
  mappings `mapping-3092` / `mapping-4124` and renderer operations 3092 / 4124.
- Each mapping contained 1,026 tiles. Its unique ImageBitmap source was 23 / 25,
  respectively, both 848x1200. Identity transform, source-over and filter none
  were observed in both the tile and renderer draws. No rotation is inferred
  from dimensions.
- The renderer used full source rectangles `(0,0,844,1200)` and destinations
  `(1430,0,998,1416)` / `(432,0,998,1416)`: a display scale is explicit.
- Existing `imagebitmap_pixel_exact_match` compared full decoded pixels without
  resize against 19 candidates per source. All 19 comparisons per source were
  available; exactly one JPEG matched each bitmap. This proves upstream tile
  JPEG attribution within the observed bounded candidate pool, not a complete
  page artifact or an original finished-page JPEG.
- A separate 400x1 HTMLImageElement was drawn to `(1230,1416,400,2)` outside
  the two body rectangles. It is not evidence of composition inside the body.
- The production selector retained a third transition geometry box and returned
  no capture. The diagnostic's two mapping-bearing calls are upstream evidence,
  not a substitute for successful production visible-page selection. A default
  `returned_path=native_png` debug field with zero captures is not PNG success.

Initial Lead classification: **D / unsupported or incomplete artifact proof**. JPEG
source identity is now established, but complete selected-visible-output proof
and the 848-to-844 partial-edge/crop/padding correspondence remain unproven for
safe source-native recovery. No B artifact contract or C/source-PNG conclusion
is adopted. R5's 38 destination-edge clips remain historical evidence; they
must not be silently counted as a fresh R7 measurement.

At that initial decision, no further manga live sample was warranted: fixing the transition
box alone would not establish the missing edge/padding and reconstruction
proof. A new partial-edge recovery contract would go beyond the bounded
attribution question. Manga 2 remains unused because no safe new recovery
pattern was established that needs cross-title confirmation. The later bounded
MCU/crop proof and successful production capture supersede this stopping decision.

## Initial post-login continuation — LN `2/314`

Actual entry was `3/314`, not an assumed page 1. Worker explicitly returned to
and verified `1/314`, probed `2/314` only, then returned to and verified `1/314`.

- The production selector chose one draw on renderer canvas 3 (2861x1418).
  Its source was canvas 4 at 1443x2048, full source rectangle
  `(0,0,1443,2048)`, destination `(931,0,1000,1416)`, identity transform,
  alpha 1, source-over and filter none. Display scale is explicit. No upstream
  rotation or padding interpretation is inferred from dimensions.
- The selected renderer operation was 2946, but `mappingId` was absent and
  `completedMappings` was empty. The trace was not generally empty: it recorded
  2,960 operations / 2,956 draws / one clear. This bounded production trace did
  not establish upstream bitmap identity or geometry for the selected draw.
  It does not prove that the site has no upstream lineage.
- Production returned one native PNG at 1443x2048 and the reconstruction path
  failed closed with `selected renderer draw mapping identity unavailable`.
- Seven JPEG candidates were compared against that returned native PNG without
  resizing. None was exact; the sole same-dimension candidate was not exact.
  This comparison is against the visible native output, **not** the previously
  observed 1448x2048 bitmap. The historical full-pixel bitmap/JPEG match is not
  contradicted or promoted into visible-output proof by this result.

Lead classification: **D**. The missing evidence is the exact selected-canvas
to upstream-bitmap mapping, including source/destination rectangles and
crop/padding/composition, followed by complete candidate-to-page attribution.
The current PNG remains a fail-closed native output; no source-PNG claim is made.

## Initial post-login continuation — LN `3/314` (superseded below)

Actual entry was `2/314`. Worker explicitly restored/verified `1/314`, navigated
through `2/314` to observe only `3/314`, then returned via `2/314` and verified
`1/314`. No previous end position was assumed.

- The production selector accepted one geometry box. Renderer canvas 1
  (2861x1418) used exact mapping `mapping-8852`, renderer operation 8852, source
  canvas 4 at 2048x1453, full rectangle `(0,0,2048,1453)` and destination
  `(431,0,1999,1416)`. Transform was identity, alpha 1, source-over, filter none.
- The selected completed segment contained 2,944 tiles from ImageBitmap source 7
  at 2048x1456. Clear operation 5903, tile operations 5908-8851 and renderer
  operation 8852 establish the observed ordering. Tile transform was also
  identity with source-over/filter none; no rotation is inferred from a
  width/height swap.
- The trace contained 8,860 operations. Exact compact fetch returned one
  requested mapping, with zero missing mappings, no reported trace overflow and
  no completed-mapping eviction.
- Full decoded-pixel comparison without resize against eight candidates was
  available for all eight and found exactly one JPEG matching ImageBitmap 7.
- Production returned one native PNG at 2048x1453. The mapping validator rejected
  reconstruction with `ImageBitmap dimensions differ from source canvas`.
  Eight JPEG candidates had zero exact matches against this native PNG, a
  separate comparison from the successful upstream bitmap match.

Initial R7 Lead classification: **D**. Selected mapping and unique upstream JPEG
identity were established, while edge coverage and complete output proof were
still missing. The image audit below supersedes those missing-output claims;
the later DCT PoC also supersedes the unsupported-recovery classification for
this exact LN `3/314` case. No source-PNG claim is adopted.

## Follow-up image audit — LN `3/314`

The user's question about the small dimension difference warranted one direct
image comparison instead of treating the initial stopping decision as final.
The branch was fetched and merged with current `origin/main` again (already
up to date at the baseline above). This synchronization is not research evidence.
Worker observed actual entry `2/314`, explicitly verified anchor `1/314`, visited
only target `3/314` via `2/314`, and restored/verified `1/314` afterward.

- Renderer selected source canvas 4 (2048x1453), full source rectangle,
  destination `(431,0,1999,1416)`, mapping `mapping-5896`. The upstream JPEG
  hash is `c6eade9c2c94d7dd7c47eb630a08765e88e1c4765f848400ac116cd11b6e0555`,
  matching the exact R7 candidate. In this new window, full-pixel comparison
  against the retained selected-mapping source object 7 was available for all
  eight candidates and again found exactly one match. IDs are window-local.
- Direct inspection of the raw 2048x1456 JPEG shows scrambled image tiles, not
  a readable page. Cropping it at vertical offsets 0, 1, 2 or 3 does not match
  the native output; approximately 99.5% of pixels differ in each comparison.
- The recorded 2,944 source rectangles cover the full encoded image. Tiles are
  32x32 or 32x16 and are copied without tile resizing/rotation. Replaying the
  exact source/destination rectangles into a 2048x1453 image fills every pixel
  once, with no holes or overlaps. It matches the native PNG at **zero differing
  pixels**. This is diagnostic RGB reconstruction, not a JPEG re-encode or a
  supported production recovery implementation.
- Clipping occurs at the **reconstructed page's bottom edge**, zero-based rows
  1453–1455 across its full 2048-pixel width. Sixty-four destination tiles cross
  that boundary. Because the JPEG is scrambled, their omitted source fragments
  are scattered through the raw JPEG; this is not simply its bottom-three-row
  crop. The visible output has no missing coverage or inserted padding.
- The JPEG has RGB 4:4:4 sampling. Every source/destination tile coordinate and
  dimension is divisible by eight. This is promising for coefficient reordering,
  but does not itself verify a recovered JPEG, its quantization/layout, or the
  final partial-MCU crop. The production uniform-tile/same-dimension contract
  has not been broadened.

Original image-audit evidence: `output/stage02-ln3-image-audit-20261008/audit.json`, SHA-256
`64443bbe278980c443309eeaf46ef62f1a662dc1bd846b0fb3770e264912e697`.
Raw JPEG, native PNG, complete selected tile metadata, full 2048x1456 RGB
reconstruction and bottom-edge strip are ignored research artifacts in that
directory. Image hashes and source-object comparison metadata are in the audit.
PASS: reconstruction/coverage assertions, restored anchor, image hashes,
unrelated `debug.log` hash preservation and `git diff --check`. No production
or test code changed; Unit/Integration/full pytest were not run for this follow-up.

Thus the uniquely attributed JPEG is the right **input for recovery**, but
saving its original bytes directly would save the scrambled transport image.
The current fallback is an implementation-support boundary, not evidence that
this page's source format is PNG or that a three-pixel difference makes JPEG
recovery inherently invalid. A next recovery investigation should preserve the
JPEG coefficients while handling the observed nonuniform tiles and final crop;
it must verify the recovered artifact before adopting B. No production gate was
weakened, and no Reviewer/Critic was required for this image-only research.

## Reopened continuation — DCT recovery proof and implementation contract

The user requested continuation for LN opening pages and manga. A fresh fetch
and merge again found `origin/main` already included. Unrelated `debug.log`
remained untouched. This preflight is not source evidence.

Worker used the stored LN `3/314` raw JPEG and exact selected mapping offline:

- SOF0 baseline, three components, 4:4:4; 46,592 source and destination MCU
  positions each covered exactly once by the observed 2,944 variable-size tiles.
- Reordered the quantized Y/Cb/Cr DCT blocks and wrote a full 2048x1456 JPEG,
  then a 2048x1453 JPEG with the same coded MCU grid. Neither step re-encoded RGB.
- Read back both artifacts: all component coefficient arrays, quantization
  tables and component table selector IDs match. The cropped JPEG matches the
  selected native PNG with zero differing pixels. Full-height JPEG pixel
  comparison is against the full-height RGB reconstruction, not the shorter PNG.
- Cropped JPEG SHA-256:
  `e34139bf76c7bb16e1852e0266299e875a468b68e17567d538043d56bf1425d6`.
  Full-height JPEG SHA-256:
  `776e97cc10f3275ce76589b73ea36e5023ce04de73c7e990fab3d6d351e62f3a`.
- `dct-poc-summary.json` SHA-256:
  `918bb0636c87c5f4cf6f29bc911a92edcafe14825bb9147e135f5f42be11dd3a`.
  Updated `audit.json` SHA-256:
  `5d1dd97c1948945f02eff88454a8aa9a472b64916a4f4bdf6d3b9c78fcc46b08`.
  Files remain in ignored `output/stage02-ln3-image-audit-20261008/`.

Lead adopts **B for this observed recovery pattern**, not for direct raw-JPEG
saving. The minimal implementation must retain separate coded dimensions S and
visible dimensions V, require S = round-up-to-8(V), prove the entire S-grid
bijection including invisible edge blocks, preserve strict source/operation/
completed-mapping identities and safe draw state, and verify output V header
plus S coefficient grid, quantization and layout. New-path intrinsic browser
pixel comparison against the selected draw-time native snapshot is mandatory
even when the optional existing final-pixel setting is off. Direct mappings
only; existing uniform/one-hop capture and spread all-or-none behavior remain.

A focused Critic accepted this narrow design with those safeguards; another
Critic gate is not needed unless the design materially changes. Worker owns
implementation and targeted/local browser tests. Bounded live verification and
Reviewer approval remain required before completion.

The first attempted LN2 access check mistakenly used ordinary CUA Chrome,
not the shared crawler CDP. Its login redirect and missing retained viewer tabs
are excluded as crawler-access evidence. Lead corrected the unnecessary login
request. OS preflight confirms Chrome listening on 9222 with `.chrome-crawler`.
The corrected `configure_run(direct)` / `prepare_page` / product navigation /
`initialize` entry through Playwright CDP succeeded: actual `3/314`, explicitly
rewound through `2/314` and verified `1/314`. Login is valid; no credential or
resource operation was needed. No target lineage is claimed from the access
checks. LN2/manga bounded provenance research resumes from the verified baseline.

### LN `2/314` bounded continuation

Correct shared-CDP probes verified actual entry `2/314`, explicit anchor
`1/314`, target `2/314`, and restoration to `1/314` in successful runs.

- `output/stage02-ln2-live-20261008/ln2-final-summary.json` re-established a
  unique full-pixel match from ImageBitmap source 2 (1448x2048) to one of three
  same-size JPEGs, hash
  `4dbc98638f1d8b5fcbbc2f59a4e7761a5b9af48142efc83e675b87c7229e061f`.
- A separate repeat run retained exact selected mapping `mapping-8848`,
  2,944 tile rows, source bitmap 1448x2048, renderer source canvas 1443x2048,
  one returned mapping, two retained mappings, no eviction. Its diagnostic
  erroneously compared the 1443x2048 cover candidate instead of the bitmap's
  1448x2048 candidates. That negative comparison is excluded.
- The local canvas observer recorded 2,944 tile draws on one actual canvas,
  but did not retain a full selected-source/output replay. Missing completed
  mapping in another window does not prove the viewer lacked a full clear or
  used an implicit resize reset. The lifecycle cause remains unresolved.
- The one corrective same-window attempt ended at the owned entry with
  `BookWalker read button did not navigate to a viewer`; a prior observer
  retry also ended before evidence collection on viewer render timeout.
  Neither failure is added to provenance D evidence. No login or resource
  switch was attempted.

LN2 remains **D** for supported recovery: the complete mapping and candidate
identity observations have not yet been joined in one verified recovery window,
and no exact candidate-to-native reconstruction is claimed. Production does
not infer an upstream mapping or add an unobserved canvas-reset recovery path.

### Manga `9/159` — corrected-window B proof

Worker used shared-CDP strict direct entry. Actual position was `1/159`;
navigation was `1 -> 3 -> 5 -> 7 -> 9`, with explicit geometry clear followed
by native arming immediately before `7 -> 9`. Restoration was
`9 -> 7 -> 5 -> 3 -> 1`, final `1/159` verified.

Production selected two body parts successfully. Exact selected mappings were
`mapping-3092` and `mapping-4124`; the diagnostic compact inventory also included
an earlier mapping, which is not treated as a third selected body part.

- Each selected segment has 1,026 tiles, no overflow/eviction, one unique
  full-pixel JPEG source match (19 total candidates, 18 coded-size candidates,
  one signature match and one full exact match per part).
- Coded size is 848x1200, visible/native size 844x1200. Recorded tile variants
  are 16x16, 16x32, 32x16 and 32x32. The full coded source/destination MCU grid
  is a bijection, including the partially visible right-edge blocks.
- Both output JPEGs are 844x1200, coefficient/quantization/component-selector
  exact. The optional old final-pixel flag was **off**, but the new-path
  comparison ran for both selected draw-time native snapshots and reported
  available, equal dimensions, zero differing pixels and zero max difference.
- Production returned `reconstructed_jpeg`, spread ready true, two JPEG parts.
  The original R7 geometry ambiguity is resolved for this corrected collection
  window; no content-label or dimension-based candidate attribution was used.
- Raw individual source hashes were not exported by this diagnostic (the
  native-call ring is not source inventory authority). Exact source identity
  is established by the production completed-mapping/object comparison proof,
  not by assigning historical hashes to current parts.

Lead classification: **B** for this observed renderer/provenance pattern.
Local helper and summary are under ignored
`output/stage02-manga-edge-probe-20261008/`. Summary SHA-256:
`4af336509611b70aad1b70a270102c22082df25a117279708982d4d2a003fe85`.
Output JPEG hashes in right-to-left order:
`cf87a40f8a9d25af44dec8e26f2c7e2121b172eda8eef19156113b3b3e7100d5`,
`c384df393523ebd8190d419f41a1c9414a9268ca7d295d951576ee6e6202a82f`.
Targeted/local tests pass. The later final live set above also completed the
second body-spread verification and LN controls. Initial production
Reviewer found no concrete wrong-artifact defect and requested one synthetic
browser-backed nonuniform/permuted right-and-bottom crop case. Worker extended
the existing Integration test (40x40 coded to 37x36 visible); the two affected
browser suites pass 46 tests. Reviewer confirmed no remaining code/test/doc
BLOCKING. The 180 targeted unit tests remain passing; no production code change
was needed for the review fix.

## Current production validation

- PASS: `uv run pytest -q tests/unit/test_bookwalker_native_capture.py tests/unit/test_bookwalker_purchased_mapping.py tests/unit/test_bookwalker_lossless_jpeg.py tests/unit/test_bookwalker_adapter.py tests/unit/test_bookwalker_original_capture.py` — 180 passed.
- PASS: `uv run pytest -q tests/integration/test_bookwalker_adapter_browser.py tests/integration/test_bookwalker_original_capture_browser.py` — 46 passed after the review fix.
- The added synthetic browser case uses a nonidentity, nonuniform tile mapping
  from a 40x40 coded JPEG to a 37x36 Canvas snapshot, cropping both right and
  bottom edges. The real browser's intrinsic comparison is pixel exact. Unit
  tests separately prove the new mandatory gate runs with its optional flag off.
- PASS: affected-file Ruff; root also ran `uv run ruff check src tests`.
- PASS: `git diff --check`. No pytest skips were reported.
- Reviewer recheck: no remaining code/test/doc BLOCKING. The initial browser
  coverage finding and the contradictory same-dimension/historical wording
  were resolved. The later final live set above completes required live
  acceptance; final evidence/document Reviewer also confirmed PASS with no
  remaining BLOCKING. Stage 02 is complete.
- Full pytest was not run: this is a BookWalker-local change with targeted
  capture tests and the affected browser-backed Integration suites passing.
  No Core/shared abstraction changed. Full-book/END live verification is outside
  this bounded acceptance set.

## Historical initial no-change closure — checks and artifact identities

This subsection describes the initial documentation/research-only closure,
before the later B classification and production implementation. Its statements
about unchanged production/tests and no pytest invocation are historical, not
the current verification status. Current results and completion decision are above.

The live helpers reused production selection, compact mapping, candidate and
full-resolution comparison mechanisms where available. R6's legacy empty trace
was excluded and replaced by the corrected R7 lifecycle. No diagnostic was
promoted into a supported production or test contract. Artifact hashes identify
local metadata; relevant observations are recorded above so a fresh clone need
not contain the ignored files. Mapping/source IDs are capture-window-local.

PASS: final JSON parsing, report SHA-256 consistency, final D fields, anchor
restoration fields, thread-limit-2 TOML parsing and `git diff --check`. The
earlier Ruff PASS below applies to the same unchanged `src`/`tests` baseline.
No pytest was invoked (zero pytest skips). Unit, browser-backed Integration and
full suite were not rerun because production and tests were unchanged. Research
trust checks were the actual-counter/anchor protocol, corrected snapshot order,
nonempty trace/exact mapping checks where available, production selector result,
existing full-pixel comparisons, and metadata/hash consistency checks. No new
synthetic producer matrix or full viewer reverse engineering was attempted.

No image bytes, signed URLs, credentials, Cookie or storage state were committed.
The remote Chrome/profile was preserved. `debug.log` remains unrelated user data.

| Metadata-only local artifact | Final SHA-256 |
| --- | --- |
| `output/stage02-manga1-r6-summary-20261008.json` | `561423769fb7b8a1f96ebf548c27151e040309a002e7e48232f6c436bb1cdb03` |
| `output/stage02-manga1-r7-summary-20261008.json` | `a549bc41bf9117725f695ea9d74ec962106c5cd727643014b4901089a66c8d94` |
| `output/stage02-ln2-r7-summary-20261008.json` | `ea84e876e5d2720310372697aa105c8ef7dd72fcaba88f607dc7fd8a822cbabf` |
| `output/stage02-ln3-r7-summary-20261008.json` | `d75461cfec7ba214f8c7f9cf9d7602bbdbe22a7c004b4cf20bd89edf46dabe8b` |
| `output/stage02-offline-audit-20261008.json` | `e5acc0ff66a94e7d6d856fb0fa76ac56f675a66268f23488353e979023eb9002` |

The final audit adds Lead's D decision to the manga R7 metadata; its earlier
upstream-only B-candidate wording is explicitly superseded. R7 manga edge-clip
count, full tile-coverage bounds, overflow and eviction fields were not retained
in the local metadata summary and remain unreported. Do not infer their values
from R5 or from a successful two-record compact fetch. The earlier LN2 hash was
superseded by the offline evidence-separation clarification; final hashes above
identify the accepted metadata versions.

## 2026-10-08 access-only precheck (historical; resolved before R6/R7)

The Lead selected one fresh manga question: can the selected ordinary-body bitmap
at `9/159` be attributed one-to-one to an exact upstream encoded source? The
Worker could not reach that anchor. No fresh source/geometry/pixel probe ran.

- Initial manga `direct` entry reached a login form; an `auto` attempt also failed
  to reach a ready viewer. A quota control lookup found no matching maruyomi
  control and did not click a resource control. These attempts are access
  observations only, not provenance probes or a supported fallback strategy.
- Configured email/password presence was true. The existing login-form helper
  submitted once in a dedicated new Page, observed a viewer destination and
  disappearing login form, then closed only that Page. No credential value,
  Cookie, storage state, or signed viewer URL is recorded here.
  An initial helper invocation could not find the home-page login button and
  submitted no form; the subsequent visible member-form submission was the
  single actual login submission.
- After login, manga strict-direct control kinds were `trial`, `unknown`, and
  `generic_reader`; no `owned` control was available, so no direct click ran.
- The independent LN strict-direct precheck observed `generic_reader`, `maruyomi`,
  `subscription`, and `unknown`; no `owned` control was available and no direct
  click ran. There was no quota/auto/trial switch for LN.
- No quota control was clicked and no resource consumption was reported. The
  cause of missing owned controls and the current account's entitlement are not
  proven by these observations.
- Actual reader counters, start/end positions, and anchor restoration were
  unavailable for both targets. No fresh `1/159`, `9/159`, `1/314`, `2/314`, or
  `3/314` position is claimed.
- The Lead requested that the user make the intended account available in the
  shared Crawler Chrome. Live operations then stopped to avoid competing with
  manual login. No new viewer/probe helper, fixture, or production code was added.

The Worker confirmed the CDP endpoint at `http://127.0.0.1:9222` and the Chrome
process's repository `.chrome-crawler` profile. Each access attempt used and
closed a dedicated Page; remote Chrome remained running. The metadata-only local
report `output/stage02-access-precheck-20261008.json` has SHA-256
`cc0507be54346bed35b108eef08a3614ffd57ac38a4e71f33128b575b0547997`.
It records the seven entry/login attempts without image bytes or secrets. Its
structural observations are summarized above so the ignored local report is
not required to understand this checkpoint.

At this precheck, Stage 02 was **not complete**. Access failure did not establish
D. Classification was retained from the historical evidence below; the later
R7 attribution above supersedes the manga's missing-upstream-source statement:

| Case | Retained classification | Still missing |
| --- | --- | --- |
| Manga cover | A (historical) | No fresh regression claim |
| Manga ordinary body | D | Exact encoded JPEG/PNG attribution and complete source/output proof |
| LN `2/314` | D | Exact selected-output lineage from the all-pixel-matched 1448x2048 JPEG/bitmap |
| LN `3/314` | D | Exact selected-output lineage, crop/padding/coded mapping and complete visible-output proof |

At this precheck, manga 2 remained unused and research stopped for target access,
not because further provenance research had been judged unproductive.

## Checks and cleanup before the post-login probes

- PASS: `.codex/config.toml` parses with `tomllib`; spawned-thread limit is 2.
- PASS: `.venv/Scripts/ruff.exe check src tests`.
- PASS: `git diff --check` after the merges and documentation/cleanup changes.
- Production Unit/Integration/full pytest were not rerun: this continuation
  changed documentation and the research thread cap only, with no production or
  durable diagnostic/test contract change. No pytest skips occurred because
  pytest was not invoked. Fresh provenance Live verification remains unexecuted;
  only the access checks above ran. Old Stage 01 test counts are historical.
- Restored `max_concurrent_threads_per_session = 2`; no reason remains to retain 4.
- Replaced the BookWalker note's universal PNG-saving scope, dedupe and packaging
  wording with the current original/reconstructed JPEG, source/native PNG and
  rendered fallback behavior.
- Reviewer/Critic were not invoked: no production change, proof-gate change,
  heuristic attribution, or broader generalization was proposed.

## Precheck resume instruction (subsequently followed)

After the intended account can open the targets in the shared Crawler Chrome,
Worker must recheck actual counters and strict access. Do not assume the login
Page's viewer destination was either research target. Resume the single
`9/159` manga spread question first; classify its evidence before deciding on a
second spread. Then probe LN `2/314`, inspect the result, and only then select
the bounded `3/314` question. Do not rerun credentials or choose another resource
merely to bypass the missing owned control.

## Historical Stage 01 / R5 evidence

- Production capture code remains unchanged.
- Stage 01 cover A and ordinary LN-text A evidence remain historical controls.
- Manga ordinary body remains D.
- LN opening remains D.
- Manga 2 has not been used.

Historical manga R5:

- actual initial position was `9/159`;
- Worker rewound and verified `1/159`;
- captured `1/159`, `3/159`, `5/159`, `7/159`, `9/159`;
- ended at `9/159`;
- restored and verified `1/159`;
- at `9/159`, two selected native PNG artifacts were 844x1200;
- selected lineage had two 1,026-tile mappings with 38 destination-edge clips each;
- exact encoded-source attribution was not proven;
- inventory contained only 158x224 JPEG thumbnails among eligible observed JPEGs.

R5 establishes bounded native lineage, not source-PNG authority or reconstructable JPEG
proof.

Its first capture used rendered fallback and is not a fresh cover-A regression pass.

## Previous diagnostic work

OBJECT-A and related local diagnostic files were developed under the previous workflow.

They were not fully reviewed and are **not production/source-format authority**.

They may be:

- reused if Lead decides they directly answer a concrete bounded question;
- ignored or retired if a simpler direct probe is more efficient.

There is no requirement to finish OBJECT-B/C or a synthetic producer matrix.

The earlier agent-thread-capacity problem no longer blocks research because normal
research now uses only Lead + Worker.

## Historical workflow-revision resume order (superseded by completion)

1. Continue on `research/bookwalker-source-native-20261005`; do not create a replacement
   branch just because `main` has advanced.
2. Fetch `origin` and merge the current `origin/main` into this branch before new
   live research or production edits. Preserve both newer main behavior and this
   checkpoint/runbook evidence when resolving conflicts.
3. Lead reads this checkpoint and the current Stage 02 README after the merge.
4. Do **not** restore Reviewer/Critic merely to satisfy the old gate sequence.
5. Pick the smallest direct unresolved manga or LN provenance question.
6. Worker performs one bounded probe.
7. Lead classifies the result A/B/C/D or asks one more bounded question.
8. Stop research when another probe is unlikely to change the operational decision.
9. If production code is implemented, invoke Reviewer.
10. Invoke Critic only if a material risk trigger in the README applies.

## Local ignored artifacts

The following hashes identify earlier local files but do not make them repository
authority:

| Local file | SHA-256 |
| --- | --- |
| `output/stage02_manga_provenance_probe.py` | `95a8c17d3801022ba2e797c69d94f1249942edf0a3351073a5e93a2514ccc634` |
| `output/stage02_create_image_bitmap_synthetic_browser_check.py` | `2174c62fb749daf425ffb1aae5ae8aa1d46aa75cf4df59cdec023549d65253af` |
| `output/stage02_create_image_bitmap_observer.py` | `c5aab98c6584b5f6d1c1439d7523503a3322f592500e08218046df1cf64c5517` |
| `output/stage02-manga-ledger/create-image-bitmap-synthetic-evidence.json` | `644d29f3fc885bc0294d699d54067b33cb0da6c397e74332632d96fcc90d2fc7` |

A fresh clone need not reproduce or complete these files unless Lead explicitly chooses
that route.
