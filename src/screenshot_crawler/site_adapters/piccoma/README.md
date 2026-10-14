# Piccoma adapter

## Implemented scope

Piccoma Discovery and the horizontal viewer/Capture adapter support unconditional free access and already active manual unlocks. Discovery validates complete product episode lists and records observed manual-unlock expiry separately from free access. The viewer adapter rechecks the target's current listing state before entry. The ordinary 1:1 display profiles first attempt the strictly proven, site-local JPEG tile replay and white composite, then encodes those RGB pixels as validated lossless WebP. If WebP encoding or exact round-trip proof fails, it retains the same verified native pixels as PNG with an encoding-fallback reason. If source attribution is unavailable before materialization, it uses the existing Core canvas/Locator PNG path.

The ordinary 1200px-high native profile admits widths 757..844 within the
live-measured width envelope, subject to complete 16x24/17x24 tile, source JPEG,
covering-white paint and generation proof. Additional widths must also prove
1:1 display within 0.01 CSS px. Size only selects a candidate grid; all exact
setup/draw, source/destination coverage, fractional draw, output dimension and
lossless checks remain mandatory. The discrete overscan/scaled profiles retain
their existing contracts. Sizes outside these bounded profiles still fall back. Locator rounding at fractional canvas coordinates can add one
pixel and remains a fail-closed fallback limitation; the 764px fix uses verified
native pixels without changing screenshot bounds or resizing images. On
2026-10-10, product/episode 6913:2770415 passed all 20 pages through explicit END
and the standard manual CLI packager, with 20 validated 764x1200 lossless WebP
ZIP members and no PNG fallback. Details, tests, and limits are in
[the current note](../../../../note/09_piccoma.md#764px-native-support-and-remaining-png-fallback-limit-2026-10-10).

Phases 03 and 04 passed independent review with BLOCKING 0. Phase 05 independently verified full and incremental Discovery, direct-only planning, and the real standard Batch-to-ZIP path for one current free episode from each product. Tester and artifact audit passed; the final independent evidence/design review passed with BLOCKING 0. Detailed results and limits are recorded below and in [runbook progress](../../../../runbooks/piccoma-free/PROGRESS.md).

The Phase 06-B/Tester PNG checkpoints are historical. Phase 06-D code review and independent live Tester verification passed with BLOCKING 0. The standard Batch-to-ZIP route produced 24 and 15 lossless WebP pages for the two selected products, with exact VP8L validation and no fallback. See the current live evidence and limits below and [runbook progress](../../../../runbooks/piccoma-free/PROGRESS.md).

The scaled native profiles explicitly support 1125x1600 (736 draws) and
1350x1920 (1053 draws), preserving full RGBA pixels in lossless WebP at the
backing dimensions. They require the observed scaled display/frame/paint path
and unchanged source, generation, output and geometry proof described below.

## Runtime pacing

Phase 07 Stage A passed independent review. The distributed root `crawler.yaml` sets Piccoma `page_turn_delay_ms` to 200 and keeps `inter_candidate_delay_ms` at 3000 with the existing stop flags enabled. Both manual CLI and Batch use the existing site-neutral settings loader and resolve this value into `RunConfig`; no Piccoma-specific fallback or shared runtime change was added. If the Piccoma setting is absent, the common 1000ms fallback still applies. The delay remains once after save/progress and before the initial `go_next`, outside the page-change timeout. Rendering stability checks remain unchanged.

Phase 07 Stage B transports all six existing fresh native-trace snapshots as JSON strings and restores full dictionaries for the same Python validators and signatures. It preserves field values and intentional nulls, rejects unsupported JavaScript values/negative zero/ambiguous or oversized payloads, and treats transport/schema errors as unknown target state so Core fallback cannot proceed without continuity proof. Independent Stage B review passed. Call count/order, source-native JPEG binding, 408-draw replay, white composite, lossless WebP method6, encode-time and post-encode verification, and DPR raw-viewport equality are unchanged.

Stage C used the reviewed object and JSON implementations with the same YAML `page_turn_delay_ms: 200` setting in four interleaved 12-page manual runs. All 48 corresponding source-native lossless WebP files were byte-identical with zero fallback. Mean normal cycle time was 3.601s (object) versus 2.743s (JSON), a measured 0.857s / 23.8% reduction in these runs; trace RPC time fell by 0.864s and JSON decoding added 0.034s. WebP method6, pacing, and page-change stability time were effectively unchanged. A dedicated 24-page Batch reached explicit END and passed ZIP CRC, lossless-member, Artifact hash/size, and Catalog checks. The fresh prepackage audit also verified all 24 per-page manifest entries, 144 native evaluations, and 144 JSON decodes, while retaining no URLs/titles/raw manifest. The final Stage C review passed with BLOCKING 0. Details and measurement limits are in the [Phase 07 profile](../../../../research/piccoma-performance/PHASE07_PROFILE.md) and [Tester report](../../../../research/piccoma-performance/PHASE07_TESTER.md).



## Bounded ordinary-width native capture (2026-10-14)

Current ordinary native admission covers integer widths 757..844 at height
1200, within the width envelope measured on live pages. Width selects a
candidate 16x24 or 17x24 grid using 50px cells; it never proves source identity
or authorizes output alone. Every page must still prove the complete unique
source and destination grids, exactly three setup events plus 384/408 draws,
fractional source-height arguments and exact partial-column dimensions, one
source image object/URL/load generation, a unique matching baseline 4:4:4 JPEG
response, covering-white paint, target/source continuity and unchanged raw
geometry. Missing/ambiguous/reset/unobserved state remains rejected. The replay
and lossless RGB WebP/native PNG encoding contracts are unchanged.

This replaces the ordinary fixed-size admission restriction that repeatedly
failed on new widths. The pre-existing discrete profiles retain their
existing tolerances and paint contracts; the two high-resolution profiles and
the special 763px overscan/alpha profile have not been generalized. Additional
ordinary widths must prove display dimensions equal backing dimensions within
0.01 CSS px, besides the existing in-frame/viewport/DPR/visibility checks.
Non-finite paint rectangles are rejected. Native admission outside the ordinary
757..844x1200 envelope or the existing discrete high-resolution profiles is
still unavailable. This is a bounded protocol proof, not automatic registration
or source attribution by dimensions. No resize/crop/resampling, looser output
dimension check, retry, timeout, access, pacing, schema, CLI or configuration
change was introduced. Source-read and trace/response bounds remain unchanged.
Additional ordinary widths require verified native capture. Unavailable or
late-invalidated source/paint proof stops before screenshot fallback, and the
adapter's `get_capture_targets` refuses Core fallback after unavailability or
timeout as well. Native PNG on WebP encoding failure remains allowed because
those pixels retain complete native proof. Previously registered ordinary
widths retain their guarded Core PNG fallback; the overscan exception remains
native-only. Core is unchanged, so `note/00_core.md` needs no update.

Item/Source 26806 (`13590:670208`, 第23話 (2)) saved no pages before failure.
Metrics `e6411cdaedcd438eb700ac8fe4e05006` show fallback
`target_canvas_identity_or_dimensions`, expected 757x1200, actual Core PNG
758x1200, and zero retries/403/429/5xx/challenge/CAPTCHA. The former size table
rejected 757px before native replay; screenshot bounds rounded fractional
coordinates outward. A bounded live probe validated all 16 pages and END:
each canvas/frame was [573.5, 0, 757, 1200], viewport [1904, 1200, 1],
inFrame=true, with 384 draws plus three setup events, one validated JPEG/load
generation and covering-white paint. The probe temporarily registered only
the candidate 757px grid in its own process, preserving every other production
validator, and changed no site DOM or bitmap. Real evidence establishes this
episode and earlier measured widths, not live coverage of every integer width.
All 88 ordinary integer widths are covered by synthetic complete-grid tests.

The pre-fix Unit/browser cases for 757/775/800/801 all failed (8 failures).
After the change, 342 focused Unit/browser cases passed (0 skipped, 37.71s).
They cover all ordinary widths, both sides of the 800/801 column-count boundary,
strict new-width 1:1 paint versus existing tolerances, non-finite rectangles,
source/grid/generation rejection, native RGB/metadata/six fresh trace snapshots,
and rejection of unproven paint. Before the final native-only fallback guard,
889 affected Unit/browser Integration cases passed (0 skipped, 281.67s).
After that guard, 20 targeted browser cases passed (0 skipped, 61.47s), covering
Core unavailable/timeout rejection, late proof invalidation, native-only source
failure, successful native RGB, and permitted verified native PNG encoding
fallback. The final affected suite passed 893 Unit/browser Integration cases (0 failed,
0 skipped, 290.51s; five existing asyncio deprecation warnings). Packaging
Unit tests passed 26 (0 skipped, 0.51s). Full repository and separate Discovery,
Policy and Research suites were not run because this change is confined to the
site-local native profile, proof and fallback contracts. Global Ruff/scoped
diff checks passed. No external-site CI dependency or real-site fixture was
added. Synthetic coverage establishes the bounded protocol contract; real-site
coverage remains the episodes and reader/account setup explicitly recorded.

Final normal CLI Batch with the native-only guard passed all 16 pages and END
in a fresh online-backup Catalog (CrawlRun 10352, ZIP 7,122,251 bytes). All
members are ordered, unique, single-frame 757x1200 VP8L with verified-white
native capture and zero native/encoding fallback. Full decode, CRC, manifest
fingerprints, Artifact SHA-256/size and completion checks passed. Normal Catalog
Item/Source/runs/artifacts remained unchanged. Metrics
`efe9f8938da74cf682a9631e16fed4f9` record one completion and zero failures,
retries, 403/429/5xx, challenge or CAPTCHA. Every page member is byte-identical
to the successful pre-guard Batch, confirming unchanged successful output.

Independent final p1 capture is byte-identical to ZIP p1. Only after production
capture, the same original tainted canvas was aligned at integer coordinates
against its proven white background on the owned QA Page. Canvas generation
remained unchanged; all RGB pixels match the independent 757x1200 screenshot
(zero different pixels/channel delta). Production does not use this QA DOM
alignment or modify the canvas bitmap. Ignored evidence/scripts:
`work/piccoma/26806-grid-family-20261014/` (final verification under `final/`).

## 773px native grid support (2026-10-14)

Item/Source 26770 (`13590:670280`, 第41話 (2)) failed before saving p1.
Metrics `f079a2ebc32247609e5253f69ca6feec` and diagnostics show native fallback
`target_canvas_identity_or_dimensions`, expected 773x1200, actual Core Locator
PNG 774x1200, and no retries/403/429/5xx/challenge/CAPTCHA. This repeats the
dimension-table coverage problem seen at 777px: 773x1200 was not registered,
so native proof stopped before replay. Subsequent live evidence shows canvas
and frame both [565.5, 0, 773, 1200]. The fallback screenshot rounds fractional
Locator bounds outward, adding one pixel. The pre-fix artificial browser case
reproduced this failure; no saved page or artifact was accepted.

The earlier 773px checkpoint registered 773x1200 -> 16 columns x 24 rows,
384 draws plus three setup events, alongside the existing observed dimensions.
Ordinary 1:1 geometry and covering-white native RGB replay apply: validated
lossless WebP by default and same-pixel native PNG on encoding/round-trip
failure. Complete unique source/destination grids, the final 23px column,
fractional source-height arguments, exact source JPEG/object/load generation,
paint/style/overlap proof, continuity, raw geometry equality and output format
checks remain mandatory. The ordinary 64,000,000-byte source-read budget is
unchanged. The former rejection of neighboring widths 772/774 is superseded
by the bounded ordinary-width proof above; height 1199 remains unsupported. No screenshot crop/resizing, dimension tolerance expansion,
automatic size registration, new configuration, extra retry or timeout change
was introduced. Core/Batch/CLI/access/pacing/max_pages/END and the overscan/scaled
profiles are unchanged; `note/00_core.md` needs no update.

A bounded live probe validated all 16 pages and END. All were ordinary
773x1200 at [565.5, 0, 773, 1200], with matching frame, inFrame=true, viewport
[1904, 1200, 1], complete 16x24 grid, one validated baseline JPEG/load generation,
and covering-white paint. The probe registered only the candidate 773px grid
in its own Python process, retaining all other production validators, and
changed no viewer DOM, bitmap or production files.

Corrected normal CLI Batch in an online-backup Catalog completed all 16 pages,
explicit END and ZIP (CrawlRun 10314, 7,547,795 bytes). All 16 ordered unique
members fully decode as single-frame 773x1200 VP8L, using verified-white native
capture with no native/encoding fallback. CRC, manifest fingerprints, Artifact
hash/size, completed status and normal Catalog Item/Source/runs/artifacts
preservation passed. Metrics `8e9837d8eac44d30ae7c43745510ecc2` record one
completion and zero failures/retries/403/429/5xx/challenge/CAPTCHA. Independent
production p1 capture is byte-identical to ZIP p1. After capture only, the same
original tainted canvas was aligned to integer coordinates against white for
QA: its generation stayed unchanged and every RGB pixel matched the independent
773x1200 screenshot. This alignment changes only the owned QA Page; production
capture does not resize, crop or repaint the viewer. Ignored evidence/scripts:
`work/piccoma/26770-773px-20261014/`.

The two pre-fix Unit/browser regression cases failed. After the fix, 31 focused
cases passed (0 skipped, 4.20s). All 688 affected Piccoma Unit/browser Integration
cases passed (0 failed, 0 skipped, 265.56s; five existing asyncio deprecation
warnings). Global Ruff and scoped diff checks passed. Existing grid/generation
rejection and native
browser RGB/metadata/fractional-coordinate cases were extended, without adding
duplicate test functions. Full repository, separate Discovery/Policy/Research
and packaging Unit suites are not required for this site-local table addition;
their code/contracts are unchanged. Live evidence covers this episode only.
The fixed-size limitation of this checkpoint is superseded by the current
bounded ordinary-width contract above. Missing native proof still uses the
existing guarded PNG fallback, which rejects a rounded dimension mismatch.

## 777px native grid support (2026-10-14)

Item/Source 26758 (`13590:670301`, 第47話 (2)) stopped before saving p1.
Metrics `69cd0ed6234943d6ad9e84a8b96b3d7d` and diagnostics record native fallback
`target_canvas_identity_or_dimensions`, expected 777x1200, actual Core Locator
PNG 778x1200, and no retries/403/429/5xx/challenge/CAPTCHA. The exact 777px
backing size was missing from the explicit observed tile-grid table, so native
validation rejected it and the existing screenshot fallback ran. Subsequent
live evidence shows canvas and frame [563.5, 0, 777, 1200]; fractional Locator
bounds round the screenshot outward by one pixel. The artificial browser case
reproduced both the original fallback failure and this 778px screenshot.

The earlier 777px checkpoint registered 777x1200 -> 16 columns x 24 rows,
384 draws plus three setup events. This is an ordinary 1:1 display using the
existing verified covering-white native RGB replay and validated lossless
WebP, with same-pixel native PNG on encoding/round-trip failure. Complete
unique source/destination grids, partial final-column widths, fractional
source-height arguments, one exact source JPEG/object/load generation,
paint/style/overlap proof, target/source continuity and raw geometry equality
remain mandatory. The ordinary source-read budget remains 64,000,000 bytes.
No screenshot resize/crop, dimension-check relaxation, wider inferred size
range, new setting, extra retry or timeout extension was introduced. If native
proof is unavailable, the existing PNG fallback can still fail closed on
fractional bounds. The former rejection of neighboring widths 776/778 is
superseded by the bounded ordinary-width proof above; height 1199 is rejected. Overscan/scaled profiles,
Core/Batch/CLI/config/schema/access/pacing/max_pages/END are unchanged;
`note/00_core.md` needs no update.

A bounded live probe validated all 16 pages and explicit END. Every page is
777x1200 at [563.5, 0, 777, 1200], frame matches, inFrame=true, viewport
[1904, 1200, 1], complete 16x24 grid, unique validated baseline JPEG, and
covering-white paint path. The probe temporarily registered only the candidate
777px grid in its own Python process and retained all other production proof
checks; it did not change site DOM, rendering or production files.

Corrected normal CLI Batch in an online-backup Catalog completed all 16 pages
through END and ZIP (CrawlRun 10300, 6,490,189 bytes). All ordered unique members
decode as single-frame 777x1200 VP8L, with verified-white native capture and
zero native/encoding fallback. CRC, manifest fingerprints, Artifact hash/size,
completed status and normal Catalog Item/Source/runs/artifacts preservation
passed. Metrics `968e54fb7c5d47e6b284cacaa15c692d` record one completion and zero
failures/retries/403/429/5xx/challenge/CAPTCHA. Production p1 was independently
captured before QA-only alignment of the same original tainted canvas at
integer coordinates against white; its canvas generation stayed unchanged and
every RGB pixel matched the screenshot. Production p1 is byte-identical to
ZIP p1. Evidence/scripts/output are ignored under
`work/piccoma/26758-777px-20261014/` and contain no committed site fixtures.

Validation: the pre-fix 777px Unit/browser cases both failed; after the fix,
28 focused cases passed (0 skipped, 4.65s). All 667 affected Piccoma Unit/browser
Integration cases passed (0 failed, 0 skipped, 271.43s; five existing asyncio
deprecation warnings). Global Ruff and scoped diff checks passed.
The existing grid rejection cases now include 777px, and native browser QA
checks exact output RGB, six fresh trace snapshots, native metadata, fractional
Locator rounding and unchanged guide/forbidden-click behavior. Full repository,
separate Discovery/Policy/Research and packaging Unit suites are not required
by this site-local table addition; their code/contracts are unchanged and the
real standard packager was verified above. Live proof covers this episode;
other unobserved backing/display variants remain unsupported/unverified.

## 763px ordinary/overscan presentation selection (2026-10-14)

Item/Source 26710 (`13590:670402`) failed before saving p1. Diagnostics for
metrics `98387211023b4ad0ae0ba5c269e0aff6` contain three stable samples in
246.627ms: backing 763x1200, canvas and frame both [570.5, 0, 763, 1200],
loaded=true, inFrame=true, viewport [1904, 1200, 1]. The previous fix incorrectly
classified every 763px backing canvas as the overscan presentation below,
rejecting this ordinary 1:1 display. This is a deterministic classification
bug, rather than evidence of slow loading or a transient off-frame transition.

Current selection uses actual display/frame/paint proof, not backing width
alone. An in-frame 1:1 763x1200 page uses the ordinary geometry contract and
covering-white paint proof, with verified native RGB lossless WebP, same-pixel
PNG on encoding failure, and the existing guarded Core fallback when native
provenance is unavailable. Fractional Locator bounds can still add one pixel;
fallback dimensions are not normalized or cropped. The overscan presentation
still requires its exact geometry and four-node paint proof, retains native
RGBA, and forbids screenshot fallback (including Core's timeout/unavailable
capture route). Unknown overscan geometry and incomplete proof remain rejected.
Source/JPEG/grid/generation/raw geometry/encoding checks, retry bounds, access,
pacing, END and max_pages are unchanged. Core has no changes; `00_core.md` needs
no update. No new setting or CLI option is required.

A bounded diagnostic probe validated all 20 pages and END on this episode:
every page is ordinary 763x1200, has 384 draws plus three setup events, one
verified JPEG/load generation, and a white ancestor covering the canvas.
The probe only substituted Python readiness observations to traverse the old
gate; it did not modify the viewer DOM or bitmap. The corrected production
adapter then passed normal CLI Batch in an online-backup Catalog through all
20 pages, explicit END and ZIP (CrawlRun 10250, 8,027,687 bytes). All 20 ordered,
unique members are fully decoded 763x1200 VP8L with verified white and zero
native/encoding fallback; CRC, manifest fingerprints, Artifact hash/size and
normal Catalog Item/Source/runs/artifacts preservation passed. Metrics
`2a4fcd75d97f4b57ac9f7855dc39cc4c` record one completion, zero failures,
retries, 403/429/5xx, challenge or CAPTCHA.

Independent live p1 QA captured production output first, then placed the same
original tainted canvas at integer coordinates against its verified white
background on the owned probe Page. Canvas generation remained unchanged;
every RGB pixel matches the independent 763x1200 screenshot, and the production
WebP is byte-identical to ZIP p1. It was visually checked without missing
tiles or viewer chrome. DOM alignment was confined to post-capture QA; no
production resize, resampling or screenshot-bound changes were introduced.
Ignored evidence/scripts: `work/piccoma/26710-763px-normal-20261014/`.

Validation: all 646 affected Piccoma Unit/browser Integration cases passed.
The initial combined selection passed 671 and failed one packaging case because
the deeply nested workspace basetemp exceeded Windows path limits (259.90s).
Rerunning all 26 unchanged packaging tests with a short workspace basetemp
passed (0.27s). Thus all 672 distinct affected cases passed, zero skipped.
The focused 9-case selection also passed. Existing cases now cover ordinary
763px native RGB output and accepted fallback targets, exact white proof,
while retaining overscan RGBA/PNG and Core timeout/unavailability rejection.
Initial default temp/cache permission errors were avoided with a writable
workspace basetemp and no pytest cache provider; no production packaging code
was changed. Global Ruff and scoped diff checks passed. Full repository,
separate Discovery/Policy and Research suites were not run because their
contracts are unchanged by this site-local classification fix. Live proof
covers this episode and the separately verified overscan presentation below;
other unobserved display variants/browser/account states remain unverified.

## 763px native-only capture support (2026-10-14)

The Item 26631 failure below is now handled by an explicit native-only profile.
A bounded live probe of `13590:670550` validated all 15 pages and END: p12
alone has backing 763x1200; all other pages are 764x1200. Each page has a
complete 16x24 grid, 384 draws and three setup events. The exact source image
object/load generation, unique JPEG response and baseline JPEG dimensions
passed the unchanged validators. The diagnostic probe changed only its Python
readiness observations to traverse p12; no site DOM or canvas pixels changed.

The overscan presentation accepts 763x1200 at display 764.265625x1202 within
0.01 CSS px, frame 764x1200, aligned left edges and canvas top=frame top-1.
Frame y must be zero within 0.01, its horizontal bounds remain inside the
1904x1200 viewport, and `inFrame=false` must match this measured presentation.
The ordinary finite DPR and all ancestor visibility checks still apply.
During an approved advance, this exact settled geometry may accumulate the
same three stable samples; an out-of-position 763px canvas still waits within
the existing deadline. Other overflow profiles/sizes/offsets remain unsupported.
No viewer resize, scroll, reflow, timeout extension or extra next click is used.

This profile requires a complete native proof to capture the full page rather
than the displayed crop. Its exact four-node paint path is CANVAS,
`PCM-viewer2_canvas_wrap`, `PCM-viewer2_zoomPageContent`,
`PCM-viewer2_zoomPageWrap`. All have matching position/1202px height; the canvas
is 764.265625px wide and the three ancestors are 764px wide. The first opaque
white node is index 3 and does not cover the canvas edge. The original strict
style/pseudo-element/transform/overlap checks are retained, with this measured
right-edge gap admitted only for this profile. The complete source-derived
763x1200 RGBA replay is preserved in lossless WebP, including alpha; no guessed
white matte, screenshot crop or resampling is applied. WebP encoding or RGBA
round-trip failure retains byte-identical native RGBA PNG. Missing/changed
source or paint proof stops before any screenshot fallback, including late
source ambiguity. The adapter's `get_capture_targets` also rejects this profile
if Core requests fallback after an adapter timeout or unavailable capture.
The source-read budget remains the ordinary 64,000,000 bytes; trace/response
bounds, generation continuity and post-capture raw geometry equality remain
mandatory. Core/Batch/CLI/config/schema/access/pacing/max-pages/END are unchanged;
`note/00_core.md` needs no update.

Live production capture of p12 passed the same source/paint/generation checks.
For independent QA after capture only, the same original tainted canvas was
moved into an isolated transparent 1:1 presentation on the owned probe Page.
No bitmap paint or resize occurred, and the native canvas generation stayed
unchanged. Alpha 252..255 and every 8-bit premultiplied RGBA value matched the
independent screenshot using round(channel*alpha/255). The screenshot's
unpremultiplied RGB differs by one in twelve grayscale pixels at alpha 252;
raw RGBA is not byte-identical, and production pixels were not normalized to
fit the comparison. The first QA setup also retained the site's gray body and
layout constraints; it was replaced by this isolated presentation. Synthetic
browser QA, using the separate fixture canvas at 1:1, matches every RGBA byte.
p12 was visually checked without missing tiles or viewer chrome.

Normal CLI Batch in an online-backup Catalog completed all 15 pages and END
(CrawlRun 10101). The 6,833,926-byte ZIP passed ordered unique membership,
full VP8L decode, CRC, manifest fingerprints and Artifact SHA-256/size. p12 is
763x1200 with preserved alpha, all others 764x1200 with verified white; all are
native lossless WebP without fallback. The first eleven members are byte-equal
to the original failed run; p12 equals the independently checked production
probe output. Normal Item/Source, failed runs and artifacts were checked
unchanged. Metrics `7a0ddca2cea04af1b9f5561df41d6ddc` record one completion
and zero failures/retries/403/429/5xx/challenge/CAPTCHA. Evidence/scripts are
ignored under `work/piccoma/26631-763px-20261014/`.

At the 26631 checkpoint, 669 affected Unit/browser Integration/packaging tests passed,
0 failed, 0 skipped (249.52s; five existing asyncio deprecation warnings).
The focused selection passed 455. Extended existing cases cover exact grid
and gap/source/generation rejection, neighboring unsupported sizes, strict
paint paths, DPR/offset geometry, bounded transition settlement, full native
RGBA WebP/PNG, no screenshot on unavailable or late-invalidated native proof,
and unchanged original/high-resolution profiles. Global Ruff and scoped diff
checks passed. Full repository, separate Discovery/Policy and Research suites
were not run because the change is site-local and their contracts did not
change. Live verification covers this episode/presentation only, not other
unobserved 763px display variants or every browser/account/reader state.

After that affected run, the final Core-fallback guard was added and verified
with four targeted browser Integration cases (4 passed, 0 skipped, 21.50s):
Core handling adapter unavailability/timeout saves no screenshot or page, and
both existing free/manual-grant Batch success paths still pass. The 669-case
selection and live success path were not repeated after this fallback-only
guard; successful direct capture does not call `get_capture_targets`. Final
Ruff and scoped diff checks passed.

## 763px page display geometry limitation (2026-10-14)

Item 26631 (`13590:670550`) saved eleven 764x1200 pages, then p12 had a
763x1200 backing displayed at 764.265625x1202, y=-1, inside a 764x1200
frame. Its x position returned to the frame, but the last eight retained wait
samples still had `inFrame=false` because of the one-pixel vertical overflow.
The approved p11-to-p12 wait exhausted 10 seconds after 85 observations.
This was unsupported backing/display/frame geometry at the failure
checkpoint, distinct from early rejection of a temporarily off-frame page.
Subsequent live source-mapping and display/paint validation established the
explicit native-only profile above; adding a size entry alone was insufficient.
The initial investigation made no capture/geometry/timeout change.
The candidate had no 5xx; the batch's lone 504 was another Item's analytics
ping. Details and evidence limits are in
[the current note](../../../../note/09_piccoma.md#763px-page-display-geometry-failure-2026-10-14).
This recorded-evidence/documentation update ran no new tests or live probes.

## Ordinary-size transition settlement (2026-10-14)

The natural Item 26535 failure below established that an approved p1-to-p2
transition counted a loaded 764x1200 canvas at x=-204 as stable three times
while its frame began at x=570, then rejected it after 242.033 ms.
Current `_wait_for_body_ready` excludes out-of-frame samples during every
already requested sequential body-page advance, except the exact native-only
763px presentation described above.
The former scaled-only size predicate was removed; all other readiness gates
and capture validation remain unchanged. An unsupported off-frame sample resets stability. Capture starts only after
three consecutive unchanged, loaded, visible samples match supported frame
geometry (the native-only 763px exception is defined above). A permanent off-frame
page still stops at the existing 10-second page-change bound with retained
failure diagnostics. No extra next click, reload, Batch retry, new resolution,
timeout extension, tolerance relaxation or pacing change is introduced.
Initial normalization, backward navigation and unrequested cursor guards retain
their existing conditions. Core, source/paint/generation/output proof and
max-pages/same-content/END behavior are unchanged; `note/00_core.md` needs no
update. The failure-time diagnostic remains enabled.

The existing browser transition test now covers 764/842/844x1200 and
1350x1920/1125x1600, with the canvas initially one frame width plus 10px left
of its final position (exactly x=-204 for the 764px fixture). A 700ms pause
must settle successfully; a permanent pause must time out, preserve the
original failure-time diagnostics after later settlement, and recover with
one total next click. Before the production fix, six ordinary-size cases
failed and four scaled cases passed. After the fix, all ten targeted cases
passed (34.79s), preserving three valid stability samples before readiness.

Normal CLI Batch `--limit 1 --max-pages 20` in an online-backup Catalog
completed all 15 pages of `13590:670650` and explicit END (CrawlRun 10033).
Only the isolated copy reset the already Completed Item to Pending; the normal
Item, Source, failed/succeeded runs and artifacts were checked unchanged.
The retained prepackage manifest records native lossless WebP, verified white
backdrop and no fallback on every page. ZIP audit passed ordered membership,
15 unique fingerprints, full 764x1200 single-frame VP8L decode, CRC, and
Artifact SHA-256/size (6,737,679 bytes). All 15 members are byte-identical to
the user's successful retry archive; p1 also matches the original failed run.
This verifies unchanged output against a prior production capture, not an
independent live source-pixel observer or the exact original pause duration.
Metrics `78990a0401ab469ebd4108e0e917e8d9` recorded one completion and zero
failures/retries/403/429/5xx/challenge/CAPTCHA. Evidence/scripts are ignored
under `work/piccoma/26535-readiness-fix-20261014/`.

Final validation: 495 affected native-capture Unit and adapter browser
Integration tests passed, 0 failed, 0 skipped (221.95s; five existing asyncio
deprecation warnings). The focused transition selection passed 10 cases.
Global Ruff and scoped diff checks passed. Packaging, Discovery/Policy,
separate Research and full-repository suites were not rerun because their
contracts did not change; the isolated live Batch exercised normal packaging
and its retained manifest/ZIP/Catalog outputs were audited as described above.
Live verification covers this 15-page episode, not every timing condition or
other work; the recorded off-frame position was reproduced synthetically.

## Body-readiness failure diagnostics (2026-10-14)

Body-readiness exceptions retain their actual wait-time geometry under
`adapter_debug.piccoma_body_wait_failure` in the existing
`diagnostics/metadata.json`. The record includes requested/expected page IDs,
preceding advance, error type/message, elapsed time, total sample count, first
sample and the last eight samples. Each sample contains active IDs, raw
viewport/DPR, frame rectangle, reader-mode counts and requested/active page
rows with canvas dimensions/rect, loaded/in-frame/visibility flags and the
consecutive stability count. These values come from existing reader snapshots;
there are no extra browser requests, screenshots or response-body reads.
Source URLs, JPEG bodies and authentication values are not added. The retained
record survives a subsequently settled diagnostics screenshot. Successful waits
add no debug field, and a new wait clears the previous failure record.

The instrumentation itself adds diagnostics only. Current readiness is
described above; capture proof, retries, timeouts, pacing, CLI and configuration
remain unchanged. For Item 26357 (`13590:3873051`),
the failed run saved p1 at 764x1200 and the user retry completed all 15 pages.
Three bounded live probes succeeded while observing off-frame p2/p3 transitions.
Transient position is a supported hypothesis; the reported failure's exact
geometry was not recorded and the natural failure was not reproduced.
The later Item 26535 (`13590:670650`) failure is now recorded: approved p2
had a loaded 764x1200 canvas at x=-204 while the frame began at x=570.
Three identical off-frame samples at 12.434, 132.279 and 241.975 ms counted
as stable, then failed the geometry check at 242.033 ms. Viewport/DPR and
reader mode were supported. This confirms early rejection of stable off-frame
geometry for this failure, before the existing 10-second wait expires; it does
not establish when or whether the page subsequently settled. The subsequent
repair extends bounded in-frame readiness to ordinary-size pages as described
above. The initial investigation changed documentation only.
Synthetic browser checks verify bounded wait errors, unchanged retained
failure samples after settlement, actual metadata.json output, bounded storage,
clearing on recovery and one next click. Details and evidence limits are in
[the current note](../../../../note/09_piccoma.md#body-readiness-failure-diagnostics-2026-10-14).

Validation: 493 affected Unit/browser Integration tests passed, 0 skipped;
the focused diagnostics/readiness selection passed 9. Ruff and diff checks
passed. Packaging, Discovery/Policy, separate Research and full-repository
suites were not rerun because their contracts did not change. The subsequent
Item 26535 investigation inspected recorded evidence and unchanged code; no
new tests or live probes were run for the documentation-only update.

## 1125x1600 scaled canvas support (2026-10-14)

Item/Source 26144 is `15876:1222987`, 第2話 (1) of がっこうぐらし！.
Normal Batch metrics `591bcab12ed84ea0acb580e26c86a353` show 13 completed
candidates followed by a pre-p1 geometry failure on this candidate, with no
403/429/5xx/challenge/CAPTCHA/retry. Fresh normal CDP entry reproduced the
failure after the existing live access check; the requested canonical viewer
URL remained unchanged. The prior 1350x1920 left-offset fix alone cannot admit
this different backing size.

All 14 pages have 1125x1600 backing, a 23x32 grid (736 draws), and 739 trace
events including context creation and two backing resets. Each complete graph
and unique source JPEG passed the existing source/load-generation/context/grid
and baseline JPEG validators in a bounded diagnostic. Total source bytes were
14,872,508. Display rects are [530.1666870117188 or 530.5, 0.5,
843.0416870117188, 1199] within frame [530.5, 0, 843, 1200], viewport
1904x1200, DPR 1.0000000298023224. The existing strict scaled four-node paint
path validates for every page. The diagnostic reached explicit END.

Current native replay supports only the enumerated scaled backing sizes
1125x1600 (23x32 grid) and 1350x1920 (27x39 grid). Both use the same observed
843.046875x1199 display profile within the existing 0.01 tolerance, left
offsets 0 or -1/3 CSS px, frame 843x1200, and top offset +0.5. Size/grid pairs
remain explicit; neighboring or same-aspect-ratio sizes are not inferred.
Both preserve the replay's full RGBA pixels in validated lossless WebP, with
the original PNG encoding fallback and finite 128,000,000-byte scaled budget.
Source binding, exact fractional draws, paint path, generation, full round-trip,
raw geometry continuity, UNKNOWN/max-pages/same-content and END gates remain
required. Transition readiness uses the existing bounded in-frame wait for
both supported scaled sizes. No renderer resize, Core/Batch/CLI/config/schema,
access eligibility or pacing change is needed; `note/00_core.md` is unchanged.

Normal CLI Batch `--limit 1 --max-pages 20` with an online-backup Catalog
completed p1..p14 and explicit END (CrawlRun 9749). A diagnostic wrapper only
copied the manifest immediately before calling the standard packager.
The 9,454,758-byte ZIP contains 14 ordered, unique, single-frame 1125x1600
VP8L WebPs. All retained manifest entries record native replay, preserved
canvas alpha, lossless WebP, and no capture/encoding fallback. Full decode,
CRC, member/manifest fingerprints, Artifact SHA-256/size and isolated Catalog
completion passed. The original Item/Source, failed runs and artifacts were
checked unchanged. Metrics `7a5aa18ab78f41b3a3fabab13cc55fa9` record one
completion and zero failures/retries/403/429/5xx/challenge/CAPTCHA.
This is a production replay audit, not an independent live raw-canvas pixel
comparison. Other products/resolutions/browser layouts remain unverified.
Evidence is ignored under `work/piccoma/26144-geometry-20261014/`.

Validation: 515 passed, 0 failed, 0 skipped (209.36s; five existing asyncio
deprecation warnings), covering `test_piccoma_native_capture.py`,
`test_piccoma_adapter_browser.py` and `test_packaging.py`. Existing parameterized
cases now cover both scaled sizes: exact grid and gap rejection, nearby-size
rejection, paint roles/styles, DPR and left offsets, capture-time mutations,
finite source budgets, native WebP/PNG encoding fallback, bounded transitions,
and exact synthetic RGBA equality against independent browser rendering of the
fixture canvas. The post-capture QA reference is aligned at integer x=200 so
odd native widths do not round up and fixed controls do not overlap it; this
corrects the initial extended QA failures without changing production pixels.
Live p1/p7/p14 were visually checked for missing tiles and viewer chrome.
Global Ruff and scoped diff checks passed. Full repository, separate
Discovery/Policy and Research suites were not run: changes are site-local and
the affected capture/navigation/output contracts are covered above.

## Scaled-page left offset maintenance (2026-10-14)

Item/Source 25718 (`13565:664249`, LEVEL.261 バオウ・ザケルガ) stopped
before p1 with `Piccoma canvas does not match the supported viewport`.
Metrics `20e65b798f99422ba2fd84516c08ae2a` recorded no HTTP/challenge/retry
failure. A fresh CDP entry rechecked the active manual grant and reproduced
the geometry failure on the same `/web/viewer/s/` target.

All 20 pages retain the supported 1350x1920 backing and 1056-event trace.
At viewport 1904x1200, DPR 1.0000000298023224, the frame is
[530.5, 0, 843, 1200] and canvas display size is 843.0416870117188x1199.
Ten pages have x=530.5; ten have x=530.1666870117188. The latter offset
(-0.33331298828125 CSS px) failed the former strict left-edge match.
The existing width tolerance already accepts this measured display width.

For the two enumerated scaled backing sizes above, the adapter accepts left offsets 0 and
-1/3 CSS px, each within the existing 0.01 tolerance. It does not accept the
intervening range. In-frame/viewport/DPR, dimensions, top offset, paint path,
source binding, complete draw grid, generation, lossless RGBA output and exact
raw geometry equality during capture remain mandatory. No renderer resize,
crop, access acquisition, pacing or shared Core/Batch change is introduced;
`note/00_core.md` needs no update. Existing unknown layouts remain unsupported.

A bounded diagnostic traversed p1..p20 and END, capturing p1/p10/p20 through
the unchanged native replay/paint proof with a diagnostic-only offset gate.
After the production fix, normal CLI Batch `--limit 1 --max-pages 25` in an
online-backup Catalog completed all 20 pages and explicit END (CrawlRun 9735).
The 22,230,635-byte ZIP has 20 ordered, unique, single-frame 1350x1920 VP8L
WebPs; full decode, CRC, Artifact SHA-256/size and isolated completion passed.
p1/p10/p20 are byte-identical to the earlier diagnostic replay outputs.
The original Item/Source, failed runs and artifacts were checked unchanged.
Metrics `9337b9f654c94e4e9f2d110de461fbee` report one completion and zero
failures/retries/403/429/5xx/challenge/CAPTCHA. This is production replay
validation, not an independent live raw-canvas pixel comparison. Other episodes
and browser layouts were not live-tested. No final prepackage manifest was
retained. Evidence/scripts are ignored under `work/piccoma/25718-geometry-20261014/`.

Validation: 365 passed, 0 failed, 0 skipped (176.77s; five existing asyncio
deprecation warnings), covering `test_piccoma_native_capture.py`,
`test_piccoma_adapter_browser.py` and `test_packaging.py`. Regressions cover
both measured offsets, unknown offsets, the existing DPR boundary, and a
capture-time change between supported offsets. Synthetic native RGBA output
matches an independent 1:1 browser screenshot of the fixture canvas; the QA
presentation resets its left position after capture to avoid screenshot
rounding. Live p1/p10/p20 images were visually checked for missing tiles and
viewer chrome. An initial QA fixture failed because its fractional-position
screenshot added a column; that comparison setup was corrected without changing
production pixels. Global Ruff and scoped diff checks passed. Full repository,
separate Discovery/Policy and Research suites were not run because this is a
site-local geometry change with the affected capture/navigation/output tests run.

## Long high-resolution episode budgets (2026-10-13)

Item/Source 25978 is `13565:662546`, LEVEL.1 清麿、正義の味方,
with 42 body pages at the already supported 1350x1920 backing size.
The original normal Batch saved p1–p26 as native lossless WebP. A fresh bounded
probe reproduced p27 with `totalOverflow=true`, a retired empty trace, and
`trace_missing_or_overflow`: the document counter included already retired
pages plus prefetch. Clearing the heavy trace did not release its event budget.
Native capture became unavailable, and the scaled Locator PNG did not match
the backing size, producing the combined format/dimensions error. The existing
strict output-size gate correctly stopped this fallback.

The 32,768-event cap now bounds simultaneously buffered events. Every trace
retirement (completed capture, eviction, target overflow or global overflow)
subtracts that trace's actual event count before clearing it. Repeated retirement
releases zero additional capacity. The separate lifetime sequence and each
canvas's mutation generation remain monotonic. Actual simultaneous overflow
still retires all heavy traces, sets the sticky document overflow flag, and
keeps only lightweight mutation monitoring. No trace is truncated or revived.
The existing 1,152-event target cap, 16 retained canvases, 128 active traces,
8 MiB snapshot transport, traversal and source-attribution gates remain intact.

After that fix, replay saved p1–p30 and then p31 exhausted the ordinary
64,000,000-byte source-read budget: p1–p30 used 62,505,281 bytes and p31's
declared source length was 2,291,582 bytes. The validated 1350x1920 scaled
profile now has a finite 128,000,000-byte per-episode budget. The 1:1 profiles
retain 64,000,000 bytes. Per-source size remains 8,000,000 bytes, with the same
declared/actual-length checks, bounded body/replay timeouts and fail-closed
exhaustion behavior. These budgets cover source reads across the episode;
they do not retain that amount of image data in Python simultaneously.
Format/dimension errors now include the capture method, native-fallback reason,
expected backing size and actual output size/type, without source URLs.

Output remains verified lossless WebP with original native RGBA pixels. Access,
navigation, END, pacing, max-pages, same-content, Core/Batch/Catalog contracts
and CLI/config are unchanged. Existing failed outputs and the normal Catalog
are preserved; validation uses an isolated online-backup Catalog and output.
Evidence is ignored under `work/piccoma/25978-trace-budget-20261013/`.

Final validation: 257 native-capture Unit, browser-backed adapter Integration
and packaging tests passed, with zero skips (160.64s; five existing asyncio
deprecation warnings). Regression cases reuse capacity after more than one
lifetime cap of released events, retire twice, still accept a complete native
trace, and then trigger genuine simultaneous overflow and verify sticky
lightweight monitoring. Scaled cases prove native RGBA output after 64 MB and
fail closed at the 128 MB budget, including the diagnostic reason. Existing
pixel, eviction, generation, original-size, fallback, END and packaging cases
also passed. `ruff check src tests` and scoped `git diff --check` passed.
Full repository, Discovery/Policy and separate Research suites were not run
because those contracts were unchanged; all changed capture/output boundaries
ran. No independent agent or independent live raw-canvas pixel audit is claimed.

Normal CLI Batch in the dedicated Catalog completed all 42 pages and explicit
END, CrawlRun 9580, with a 52,113,477-byte ZIP. The retained prepackage manifest
confirms native RGBA lossless WebP and no fallback on every page. Audit checked
ordered manifest/ZIP membership, single-frame 1350x1920 VP8L decoding, 42 unique
hashes, CRC, Artifact SHA-256/size and isolated Catalog completion. All first 26
members are byte-identical to the original failed Batch's saved WebPs; the first
30 also match the fresh replay probe. Remaining pages have the production
per-capture source/trace/round-trip proof, without a separate pixel reference.
The 42 distinct observed JPEG responses total 87,537,514 bytes, within the new
scaled budget. Normal Item/Source fields and failed outputs remained unchanged.
Metrics `cd8ddd25fc4f46549dfc523a39f46add` and ignored `before.json`,
`capture.json`, `retained-manifest.json`, `audit.json`, `batch.log` and
`final-tests.log` record this bounded result. Episodes exceeding 128 MB or
missing native proof can still stop; scaled screenshot fallback remains subject
to exact backing-size validation.

## RGBA lossless WebP output (2026-10-13)

The 1350x1920 scaled profile now prefers lossless WebP while preserving every
RGBA byte of the verified replay, including alpha and RGB beneath alpha zero.
`encode_lossless_webp` and its PNG-fallback wrapper take site-local
`preserve_alpha=True` for this profile. Pillow encodes RGBA with lossless method 6
and `exact=True`, then the decoder's complete RGBA stream must equal the input.
The container must still be one valid VP8L chunk with the expected dimensions,
version and no additional chunks; alpha is admitted explicitly. The default
RGB path retains its original no-alpha container check and exact RGB proof.
Generic Piccoma result validation accepts both proven RGB and RGBA lossless
VP8L payloads, continuing to reject lossy, animated, malformed or wrong-size data.

Successful scaled output is `native_tile_replay_lossless_webp`, image/webp,
lossless=true, source_native=true, source_mime=image/jpeg, and
source_backdrop=canvas_alpha_preserved. No white matte, resizing or RGB-only
conversion is applied. Codec failure or any RGBA round-trip mismatch retains
the original byte-identical RGBA PNG and records the encoding-fallback reason.
Unknown source/paint/generation states still fail closed under the existing gates.

The first normal Batch attempt captured two WebPs, then stopped during the
third page transition. A bounded follow-up observed active p7's otherwise
correct scaled canvas at x=-322.5, outside the x=530.5 frame, before it settled
to the supported position. A page can be marked current for three unchanged
samples before its movement begins. During any already requested sequential
body-page transition, `_wait_for_body` now excludes out-of-frame canvases
from readiness and waits within its existing deadline. It still requires three
stable, in-frame samples and the full strict geometry proof. No extra clicks,
timeout extension or dimension tolerance was introduced. A permanent off-frame
canvas times out; capture never starts there. This is observed transition
settlement, not an encoder or source mapping failure.

Core, access eligibility, manual-grant semantics, pacing, output schema, CLI,
max-pages and same-content guards remain unchanged. Shared `note/00_core.md`
needs no synchronization. Evidence for this update is ignored under
`work/piccoma/rgba-webp-20261013/`; original saved PNG archives and the user's
normal Catalog remain intact. Existing completed Items are reset only in the
dedicated test Catalog to exercise the exact target again.


Final validation: 255 passed / 0 failed / 0 skipped (160.54s, six existing
asyncio deprecation warnings): `tests/unit/test_piccoma_native_capture.py`,
`tests/integration/test_piccoma_adapter_browser.py`, and
`tests/unit/test_packaging.py`, using the short workspace-local basetemp
`output/p13f`. Focused WebP/scaled cases passed 18. Tests cover partial alpha,
RGB hidden under alpha zero, deliberate corruption of each RGBA channel,
byte-preserved PNG fallback on codec/proof failure, the old RGB/native paths,
exact independent browser RGBA comparison, bounded delayed/permanent off-frame
transitions with exactly one click, and packaging. An initial fixture assumed
WebP always decodes as mode RGBA; it was corrected to compare converted RGBA
pixels, since an entirely opaque lossless WebP may decode as RGB. Full repository,
Discovery/Policy and separate Research suites were not rerun because their
contracts did not change; all capture/format/navigation/output boundaries ran.
Global Ruff and diff checks passed. No tests were skipped.

Normal CLI Batch in the dedicated Catalog completed 13565:664316, all 22 pages,
END, CrawlRun 9465 and one all-WebP ZIP. All 22 decoded 1350x1920 RGBA streams
exactly equal the prior validated PNG archive's RGBA streams, including alpha.
Every member is a simple alpha-bearing VP8L image. CRC, ordered filenames,
decoded dimensions, Artifact SHA-256/size and the original Item's unchanged
Completed state/completion time passed. The ZIP decreased from 54,220,125 to
25,194,328 bytes (53.53%); summed page payloads decreased from 54,385,410 to
25,189,334 bytes. This is a measured comparison for this episode only.
Metrics `068cc88861e349d49e3462e764519bc6` recorded one completion, zero failures,
retry/403/429/5xx/challenge/CAPTCHA. Evidence: `final-affected-tests.log`,
`final-targeted.log`, `capture-probe.json`, `final-batch.log` and `zip-audit.json`
in the ignored directory above. The failed pre-settlement-fix run remains in
the isolated Catalog. No retained final manifest or independent live raw-canvas
RGBA readback is claimed; the reference is the previously validated PNG replay.
Other high-resolution routes and external readers beyond Pillow/browser/ZIP
validation were not tested.

## High-resolution scaled canvas maintenance (2026-10-13)

Item/Source 25656 is `13565:664316`, LEVEL.323 最終話 ガッシュからの手紙.
The normal Batch completed 21 preceding candidates, then three attempts stopped
before p1 capture with `Piccoma canvas does not match the supported viewport`.
The posted Kadocomi log was an older run; local Piccoma metrics and diagnostics
identified this separate failure. Fresh ordinary entry checked an already active
manual grant and the same `/web/viewer/s/13565/664316` route. No access acquisition
or resource consumption was performed; quota remains quota, not free.

All 22 body pages use a 1350x1920 backing canvas displayed at exactly
843.046875x1199, inside an 843x1200 frame at the supported 1904x1200 viewport.
This original observation has aligned canvas/frame left edges; the current
profile also accepts the observed -1/3 CSS-pixel left offset described above.
Canvas top remains frame top + 0.5. The former 1:1 geometry rule rejected
this downscaled presentation. The current strict profile requires these
measured dimensions/offsets, existing in-frame/viewport/DPR and
ancestor visibility proof, and exact raw geometry equality throughout capture.
It returns the backing size for output; no crop, display screenshot, forced
canvas resize, or reflow is used by production capture.

Each page has exactly 1056 trace events: context creation, two backing resets,
and a complete 27x39 grid of 1053 image draws. The final destination row is 20px;
the exact source heights are 50.01 or 20.01. Source object/URL/load-generation,
unique first-party baseline JPEG response, exact context/draw arguments and
complete unique source/destination grids remain mandatory. Current scaled
native support enumerates this 1350x1920 grid and the separately verified
1125x1600 grid described above; nearby/unknown sizes are not inferred as supported.
Per-target trace capacity is 1152 events; the bounded simultaneous event total
is 32768 and retired traces release their capacity. Retained canvases (16), active
traces (128), 8 MiB full-JSON transport, 131072 traversal nodes, 8,000,000-byte
per-source budget and replay-time limits remain unchanged. Current episode
source-read budgets are 128,000,000 bytes for this scaled profile and
64,000,000 bytes for the 1:1 profiles, as described above.
JavaScript limits now derive from the Python constants. Overflow still retires
heavy traces and keeps lightweight generations; it never truncates accepted proof.

The visible canvas is 0.046875 CSS px wider than its white paint ancestors.
Their exact four-node path is CANVAS, `PCM-viewer2_canvas_wrap`,
`PCM-viewer2_zoomPageContent`, and `PCM-viewer2_zoomPageWrap`; the latter is the
first opaque white node. The ordinary covering-white proof correctly fails.
Fresh replay alpha ranged 252..255 on every real page, so dropping transparency
or guessing an edge matte would change pixels. This profile instead preserves
the verified replay's entire native RGBA pixels in lossless WebP. Its paint-path validator
requires the exact roles, measured small width difference, matching offsets and
height, unchanged strict styles/pseudo-elements, and no overlapping descendants.
It explicitly does not claim covering white. Original covering-white gates and
WebP/RGB round-trip behavior on 764/842/844x1200 remain intact.

Output now uses `native_tile_replay_lossless_webp`, `source_native=true`,
`source_mime=image/jpeg`, `source_backdrop=canvas_alpha_preserved`,
`output_format=image/webp`, `output_lossless=true`, and no fallback reason.
The lossless encoder preserves every RGBA byte; PNG is retained only on an
encoding/proof failure, with an explicit reason. A missing source/paint/generation proof still cannot silently
accept a smaller display screenshot: existing output-size and continuity checks
fail closed. Reader ordering, resume cancellation, END, max-pages, same-content,
access eligibility, pacing and shared Core/Batch/Catalog contracts are unchanged.
No CLI/config/schema change or `note/00_core.md` update is needed.

Before the RGBA WebP change, a bounded production-adapter probe captured
p1..p22 as PNG and reached explicit END.
Normal CLI Batch `--limit 1` using an isolated online-backup Catalog then completed
all 22 pages with END, CrawlRun 9446 and one ZIP Artifact. Every ordered member
matched the fresh production source-replay PNG hash/length, decoded as
1350x1920 RGBA with alpha 252..255, and passed CRC. Artifact archive hash/size
matched. The normal Item remained Pending with its failed runs preserved.
This compares the production replay twice, not an independent live source observer.
Metrics `e3e7f13650e1489ba6af4b88253c2224` recorded 1 completion, no failures,
retry, 403/429/5xx, challenge or CAPTCHA. The isolated planning skips are not
test skips. Evidence is ignored under `work/piccoma/25656-geometry-20261013/`:
`all-geometry.json`, `capture-proof.json`, `batch.log`, `zip-audit.json` and test
logs. JPEG bodies/signed URLs are not committed. Other high-resolution works,
different geometry and an independent live RGBA readback remain unverified.


Initial scaled-PNG maintenance validation: the affected selection covered 313 Piccoma Unit/browser
Integration cases and 26 packaging cases, all ultimately passing with zero
skips. The final combined invocation had 338 passed and one Windows long-path
failure in the packaging fixture (152.84s, 11 existing asyncio warnings); all
26 packaging cases then passed with a shorter workspace-local basetemp (0.34s).
An earlier invocation hit 37 setup errors because the sandbox could not write
the default user Temp pytest directory; this was resolved with a workspace
basetemp. Its historical hardcoded global-overflow fixture was also updated to
exercise the actual bounded limit rather than the old 20000-event value.
Focused grid/paint/RGBA cases and 35 geometry/scaled browser cases passed.
Synthetic browser QA compared every RGBA byte against a separate 1:1 screenshot
of the original tainted fixture canvas, after production capture; this changes
QA presentation only, not production viewer rendering. Live p1/p11/p22 PNGs
were visually inspected without missing tiles or viewer chrome. Ruff and diff
checks passed. Full-repository and separate Research/Probe suites were not run:
changes are site-local, and the affected selection covers original native
WebP/PNG fallbacks, source/paint/async guards, trace overflow/eviction, resumed
entry, navigation/END, Batch/Discovery and packaging. There is no separate
independent agent review or independent live source-pixel observer for this fix.

## Discovery and identity

Watchlist targets use a canonical HTTPS viewer URL:

```text
https://piccoma.com/web/viewer/{product_id}/{episode_id}
```

Discovery opens the matching `/web/product/{product_id}/episodes` listing. It buffers and validates the complete list before yielding: declared and observed counts must match, the product heading and every row must match the requested product, IDs must be unique numeric values, titles and status wrappers must exist, and the target episode must be present. Native DOM order is oldest-to-newest. Discovery yields latest-to-oldest and assigns whole-work display position as original DOM index + 1 before inclusive bounds are applied. Source identity is `{product_id}:{episode_id}`; caller-owned `work_key` does not encode product identity.

## Access classification

Unconditional free requires exactly one `PCM-epList_status_free` marker across the status wrapper and descendants plus exact visible `¥0`. Conflicting markers map to unknown. A recognized wait-free status maps to quota, a positive point price maps to paid, and ambiguous/missing signals remain unknown. Personal readability and generic status labels do not prove unconditional free access.

Manual unlock evidence requires the sole prefixed marker `PCM-epList_status_waitfreeRead` and normalized text `閲覧期限 残りN時間` (positive whole hours, at most three digits). Discovery keeps `access_mode=quota` and records `access_granted_until` as the observation start plus `N-1` hours, reserving one hour because display rounding is unverified. This is a conservative eligibility bound, not an exact site expiry; `free_until` is unused. All validated rows set `access_checked_at` and explicitly observe the grant field, clearing previous grants when a valid countdown disappears. Unknown/conflicting markers, zero hours, minutes, and other unobserved countdown forms establish no grant. A one-hour display is excluded from Batch.

Both full and incremental Discovery refresh every row in the requested scope. Manual unlocks can change on old episodes, so Piccoma continues past known rows. The complete listing is already buffered; this adds no listing navigation. Incremental keeps its generic semantics of not marking unseen sources unavailable. Rediscovery preserves completed Items and artifacts.

At viewer initialization, the adapter opens the product listing again and requires the unique target to remain exact-free or to have valid manual-unlock evidence with a future conservative bound. It then requires HTTP 200 and matching product/episode identity; `/web/viewer/s/{product}/{episode}` is accepted only after fresh manual-grant evidence. The accepted final URL must remain unchanged during reader operations/capture. Canonical Catalog and manifest source URLs stay `/web/viewer/{product}/{episode}`. `auto` and `direct` share this route; quota and other unsupported strategies stop without fallback. The caller's work key remains opaque metadata.

## Batch policy

The registered `PiccomaSitePolicy` admits available free sources as `direct` (`free`), and available quota sources with an aware future `access_granted_until` as `direct` (`active_manual_grant`). Neither consumes quota. Missing/expired grants and unsupported modes are excluded; malformed/naive timestamps fail closed. The policy exposes no quota/access resources, grant-only support, or additional passes. The generic Planner retains Catalog ordering, composite identity, display position, and metadata. Standard Batch execution performs stale-candidate validation and fresh free/manual-unlock checks before viewer entry. No automatic ticket, point, coin, waiting, or purchase operation is implemented. Existing `discover` and `batch run` commands need no new flags; rerun Discover after manually unlocking episodes.

A local Playwright fixture test exercises the standard Planner, `BatchExecutor`, `CrawlerRunner`, adapter, manifest, packager, and Catalog completion path using a synthetic three-page episode for both free and active manual-grant sources. Failure fixtures cover stale-free/stale-grant state, a wrong composite identity, and a redirected viewer; they assert no ZIP, no completed Item/Artifact, and no resource mutation. Discovery integration verifies an old grant beyond the generic known-row boundary, Batch eligibility, explicit clearing, and completed Item retention. Historical Phase 05 separately verified live Batch for free episodes.

## Viewer and capture

The supported observed reader is horizontal and has body classes `PCM-stt_horizontal` and `PCM-prop_scroll_l`. Body wrappers must form a complete contiguous `p1..pN` list, with one additional `last` wrapper. The observed page sequence was p1 through pN using the in-episode next control; native DOM wrapper order is reversed. A page is ready only when its expected ID is uniquely active and its single canvas is loaded, stable, and fully visible through every ancestor. The adapter advances only through the in-episode next control and waits for each expected ID. It accepts terminal END only after advancing from pN to the active `last` wrapper containing `#js_viewerEnd`.

On entry, an exact known resume prompt is automatically canceled after validating its structure, text, and two expected enabled buttons. The adapter waits for it to close, returns to p1 if necessary, and verifies a loaded, stable first page before starting capture. It never uses the resume action to start midway. The observed prompt variants are the numeric-page wording and the exact last-page wording (`前回最後のページを 読んでいました。 最後のページに移動しますか？`); mixed wording or extra text is rejected. Attachment is bounded; unknown/ambiguous dialogs fail closed. This existing cancel-to-p1 behavior was live-verified on 6913:2770415 on 2026-10-10 after closing at p2 and reopening; the first capture was p1. The one known non-interactive #js_scrollTypeSing reading-direction guide is hidden only for capture after validating one of the two observed root class sets (base class alone, or base plus `_sh` and `_show`), the same exact two child groups and three expected image labels/classes, lack of meaningful text/interactive nodes, and empty pseudo-elements; its prior inline style is restored afterward.

The owned Page starts at 1904x1200 before navigation. The horizontal viewer accepts only that viewport and a finite numeric DPR within `1e-7` of 1.0. This narrow allowance covers the live Chrome reading `1.0000000298023224` (about `3e-8` above 1) while rejecting ordinary scaled modes such as 1.25x and 2x; the raw viewport array must still match exactly before and after each capture. The tolerance changes no canvas, frame, renderability, source, or draw geometry checks. Synthetic browser tests cover an unchanged near-1 DPR capture and fail-closed behavior when DPR changes within the supported band during capture. The bounded live verification and its limits are recorded below. Live raw canvas readback raised `SecurityError`. For ordinary 1:1 display profiles, the adapter proves one loaded JPEG response's exact URL and image load generation against a complete single-image trace with an explicitly observed 384- or 408-draw tile grid, replays the exact fractional draw arguments and context state into a detached canvas, and composites the transparent result over a proven solid-white backdrop. The white-paint proof requires computed `background-clip:border-box`, `clip:auto`, no border widths/radius, and the other validated covering-area conditions. Per-target dimension observers detect same-value attribute resets even while the canvas is detached and are bounded to source candidates/current capture targets. For the 1:1 display profiles, native output is lossless WebP encoded from verified source-derived RGB pixels; the payload must be a single VP8L chunk, decode at the expected dimensions, and reproduce every RGB byte. Raw tiled JPEG bytes are never page output. If WebP encoding or round-trip validation fails, the same verified native pixels remain PNG with an explicit encoding fallback reason. If source attribution is unavailable before materialization, Core `capture_locator` remains PNG and is accepted only while the active canvas generation stays unchanged for the entire capture. A canvas mutation during either path fails closed. Source response URLs and raw source JPEG bodies are not exposed in manifests/logs or committed; verified output page images are saved normally.

The bounded Phase 06-C p1 audit confirmed `jpeglib.read_dct` can parse the exact observed JPEG responses, but the unchanged Jump+ coefficient-feasibility helper rejected both Piccoma mappings as `tile_geometry_not_mcu_aligned`. The sources are baseline 8-bit 4:4:4 JPEGs with 8x8 MCUs. The 408-draw traces use 50-pixel tiles, 44/42-pixel edge widths, fractional source height `50.01` to destination height `50`, and image smoothing enabled at quality `low`. Existing Jump+/Magapoke coefficient permutation requires integer, equal-size, MCU-aligned rectangles; it does not apply to this observed geometry. This conclusion is limited to that existing method and does not assert that every conceivable custom JPEG transform is impossible. The equal-50-height seam/phase analysis is diagnostic only; production rectangles are never rounded or normalized. Phase 06-C output was reconstructed/composited PNG; Phase 06-D keeps the same pixels and replay proof but encodes the current default native output as lossless WebP. The independent evidence/design review passed with BLOCKING 0. Sanitized evidence is ignored at `output/piccoma_experiment/source_capture_research/phase06c_jpeglib_p1_evidence.json`.

## Live evidence and limits

On 2026-10-10, product 28600 full and incremental Discovery each refreshed all
432 rows in a dedicated Catalog, recording 32 manual grants. Normal planning
selected those 32 grants as non-consuming `direct` candidates (63 candidates
including 31 free). The manually unlocked 28600:1910236 reader used the observed
`/web/viewer/s/` route and passed standard Batch through all 22 pages, explicit
END, ZIP packaging, and dedicated Catalog completion. Ordered members, CRC,
unique hashes, full decode, 844x1200 VP8L WebP, and p1/p12/p22 visual QA passed.
No grant/quota consumption was recorded and no acquisition control was used.
The normal Catalog was unchanged. Evidence, limits, and current test results
are in [the current note](../../../../note/09_piccoma.md#manual-unlock-live-verification-2026-10-10).

Historical Phase 06-B live evidence on 2026-10-09 rechecked the exact-free listings and composite identities for 28600/1910027 and 28606/2001009. Product 28600 had 24 body pages; p1, p12, and p24 were captured as 844x1200 PNGs before explicit active END. Product 28606 had 15 body pages; p1, p8, and p15 were captured as 842x1200 PNGs before explicit active END. The reading guide was present and restored after each capture. These PNG artifacts validate the earlier output format only. Sanitized evidence is under ignored `output/piccoma_experiment/phase03_b_live_capture_evidence.json`.

Phase 05 verified the live route `Discovery -> Catalog -> Batch -> Crawl -> Manifest -> ZIP` for 28600/1910027 and 28606/2001009. Both targets were freshly observed as free before entry, stayed on the requested URL, reached explicit END, and produced ordered unique body pages. The 24-page 28600 ZIP contains 24 manifest members at 844x1200; first/middle/last visual checks were p1/p13/p24. The 15-page 28606 ZIP contains 15 members at 842x1200; checks were p1/p8/p15. CRC, exact membership, capture hashes, Catalog Artifact hashes, completed Items and succeeded END runs passed independent audit. First/middle/last images for both episodes were visually checked. Image SHA256 audits were unique across all 24 and 15 pages, with zero duplicate groups. See ignored `output/piccoma_experiment/phase05_tester/evidence/phase05_tester_report.json` and `phase05_final_independent_audit.json`; these local reports and image/ZIP artifacts are not committed.

Phase 06-D current-format live verification used isolated test data. Full Discovery exhausted 432 rows for product 28600 and 218 for 28606; incremental Discovery saw five known rows per product and stopped at `known_streak`. The read-only plan had 444 direct eligible candidates, 206 skipped non-free candidates, and zero quota candidates. Exact-free targets 28600/1910027 and 28606/2001009 produced 24 pages at 844x1200 and 15 at 842x1200. All 39 used `native_tile_replay_lossless_webp`, exact observed JPEG response binding, verified solid-white composite, `image/webp`, lossless=true, and no fallback. Independent VP8L parsing validated output format and dimensions. Ordered page IDs, distinct per-episode hashes, exact ZIP/Manifest membership, CRC/member hashes, Artifact hash/size, completed Items, succeeded END Runs, and present Artifacts passed. Six current same-page Core RGB comparisons (p1/p13/p24 and p1/p8/p15) had zero changed pixels and were visually checked. The historical 39/39 PNG RGB comparison is secondary. Source/free rights fields remained unchanged, quota resource rows remained zero before and after, and no entitlement action occurred. Across these 39 pages only, 28600 measured 26,159,334 source JPEG bytes to 18,055,076 WebP bytes (-30.98%), and 28606 measured 11,187,021 to 7,300,976 bytes (-34.74%); aggregate was 37,346,355 to 25,356,052 bytes (-32.11%). All WebP pages were smaller than their observed source bodies in this run, not a general size guarantee. The Tester report is ignored at `output/piccoma_experiment/phase06d_tester/runs/20261009T073152Z-3e91e9e0/evidence/phase06_tester_report.json`.

The historical Phase 06-B PNG check validated the observed horizontal layout at a 1904x1200 viewport and DPR 1. Six selected pages used `native_tile_replay_png` with `source_native=true`, `source_mime=image/jpeg`, and `source_backdrop=verified_solid_white`; all six matched the clean Locator screenshot pixel-for-pixel in RGB. The shared-CDP performance probe later observed DPR `1.0000000298023224` on the same viewport, which the former exact-1 comparison rejected. The adapter now permits only finite numeric values within `1e-7` of 1 and compares the raw viewport exactly across capture. Updated code passed bounded live verification: two isolated runs captured p1..p12 in order, 24/24 `native_tile_replay_lossless_webp` pages, zero fallback. The runs stopped at `max_pages`; END was not confirmed and this is not a replacement for the historical full-episode verification below. Across 20 normal capture-start-to-next-capture-start cycles, mean was 4.538 s, median 4.151 s, p90 5.627 s, and maximum 5.772 s; the separate p1 cycles were 5.571 s and 5.398 s. The 1,000 ms pacing, method-6 encoder, and existing object-form trace return remained enabled. See the [full stage profile](../../../../research/piccoma-performance/PROFILE.md#full-current-pipeline-live-profile-handoff-two-runs) for detailed measurements and limits. Other layouts/resources, unobserved draw graphs, and altered backdrop structures remain unsupported and fall back or fail closed. Catalog `last_seen_at` was populated, but `access_checked_at` remained NULL after live free-entry verification. Redirected Windows CLI output for `batch plan` initially failed under cp932 on title U+8E20; rerunning with task-local `PYTHONIOENCODING=utf-8` and `PYTHONUTF8=1` passed without title loss or code changes. No ticket, waiting, point, purchase, rental, unlock, CAPTCHA bypass, or DRM bypass flow was used.

## Tests

Phase 03 review passed with BLOCKING 0 (174 passed, 0 skipped). Phase 04 review passed with BLOCKING 0 (130 passed, 0 skipped); local policy/CLI tests passed (96), Piccoma Batch browser integration passed (34), and the combined affected suite passed (310, 0 skipped). Phase 05 and Phase 06-B live Tester/audit evidence covers the historical PNG output. Phase 06-C was a bounded read-only coefficient feasibility probe; its findings are recorded below. Phase 06-D Piccoma native-capture unit/browser tests passed (99, 0 skipped), packaging tests passed (26, 0 skipped), and Ruff/diff checks passed. The cross-page regression covers native PNG after encoder failure, Core PNG after an unsupported operation, native WebP recovery, and metadata reset after failed capture. Independent Phase 06-D code review and live Tester both passed with BLOCKING 0; all 39 pages passed the standard Batch-to-ZIP route. The full suite was not rerun after the final site-local adjustments; the earlier 1881-pass run was on the reviewed checkpoint immediately before the final NamedNodeMap compatibility fix. That fix was tested separately, and the suite was not rerun afterward. Downstream WebP reader compatibility outside the tested browser/Pillow/ZIP validation was not separately verified. No copyrighted payloads, source-image bytes, signed URLs, or authentication data are committed.
