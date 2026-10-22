# Piccoma current implementation snapshot

## Shared work-key scope inventory (2026-10-22)

Piccoma Discovery exposes complete product-listing identity/position evidence
after a successful Full traversal. That evidence is distinct from free, paid,
wait-free, or manual grant state. `watch scope-sync` applies acquisition flags
only after the Watchlist boundaries and Full proof are validated; Batch does
not resolve the boundaries online. No paid, ticket, quota, or live-site action
was performed for this shared change.

Updated: 2026-10-14. Phases 01-05 remain accepted. Phase 06-B's source-derived PNG replay and Phase 06-C's bounded p1-only JPEG coefficient feasibility work are historical accepted checkpoints. For the 1:1 display profiles, Phase 06-D defaults verified replay pixels to lossless WebP, retaining native PNG if encoding/round-trip proof fails and Core PNG if native provenance is unavailable. Phase 06-D code review and independent live Tester both passed with BLOCKING 0. Local Piccoma tests passed 99, packaging tests 26, and Ruff/diff checks passed; the full suite was not rerun after final site-local adjustments. The current two-product live route verified all 39 WebP pages through ZIP and Catalog completion. Phase 07 Stage A/B passed independent review. Stage C's interleaved manual comparison, 24-page Batch END/ZIP/Catalog run, and fresh per-page manifest audit passed; final Stage C Reviewer review passed with BLOCKING 0. Evidence and limits are in the [Phase 07 live profile](../research/piccoma-performance/PHASE07_PROFILE.md) and [Tester report](../research/piccoma-performance/PHASE07_TESTER.md).



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

## 763px page display geometry failure (2026-10-14)

Item/Source 26631 (`13590:670550`, 第109話 (1) of 暁のヨナ) saved
p1..p11 at 764x1200, then failed while waiting for p12. Its retained
`piccoma_body_wait_failure` records 85 observations over 10,016.920 ms,
requested p12, expected cursor p11 and an approved advance from 11.
The first observation at 15.003 ms has loaded/visible p12 with backing
763x1200 and display rect [-204, -1, 764.265625, 1202]. The last eight
observations, 9,080.945..9,916.499 ms, have rect
[570, -1, 764.265625, 1202], frame [570, 0, 764, 1200], viewport
[1904, 1200, 1], loaded=true, inFrame=false and stability count zero.
Horizontal position returned to the frame; the displayed canvas still extended
one CSS pixel above and below it. This violates the current in-frame gate and
ordinary 1:1 backing/display/frame geometry contract. The new bounded wait
therefore correctly exhausted its existing deadline; this is not the former
242ms early rejection. The trace does not show every intermediate observation
or establish what happened after the timeout.

At the failure checkpoint, the 763x1200 backing/grid was absent from the
native whitelist and an existing test explicitly rejected it. Adding a size
entry alone would not address its display/frame mismatch. Subsequent live
validation established the explicit native-only profile described above. The
initial investigation changed documentation only; the current implementation
retains all general geometry gates and makes no renderer/timeout changes.

Metrics `30e0cad691eb471d8d71d7d45608c9ba` show 65 completions before this
candidate failed. Its requests had no 5xx; the batch's single 504 belonged to
Item 26605's `analytics.tiktok.com` ping, not this candidate. No 403/429,
challenge, CAPTCHA or retries were recorded for the batch. Evidence is in
`output/batch/piccoma/item-26631-source-26631-20261014T150909610686+0900-b1ff41ed72d049d893de902dff7d2129/diagnostics/metadata.json`
and its retained manifest. This was recorded-evidence/code inspection only:
README/note updated; no new tests, full suite, Research or live probe run.
Core implementation is unchanged, so `note/00_core.md` needs no update.

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

Item/Source 26357 (`13590:3873051`, 第244話 (1) of 暁のヨナ) failed
after saving p1 as a 764x1200 native WebP. Metrics
`56b91b55c9fd4308bd21c6e30033f3d4` recorded 46 completed candidates then
this geometry error, without HTTP/challenge/retry failures. The failed run
9819 is preserved; user retry run 9820 completed all 15 pages and END.
The original diagnostics contain `detected_state=content`, which is the last
Runner state passed to diagnostics, not a fresh reading of the failing wait.
They did not retain the failing wait-time geometry, so its exact cause cannot
be proven retrospectively.

Three bounded, unmodified-adapter CDP probes captured p1/p2 and reached p3.
All succeeded, while snapshots observed the 764x1200 canvas temporarily
outside the [570, 0, 764, 1200] frame during p2/p3 transitions before settling.
This supports a transient-position hypothesis, not reproduction of the exact
reported failure. At the diagnostics-only checkpoint, the ordinary-size
readiness path could reject an off-frame canvas after three unchanged samples;
only the two enumerated scaled sizes excluded off-frame samples while waiting.
That checkpoint added diagnostics only; the subsequent readiness repair is
described above. Timeouts, retries, capture/source proof and pacing are unchanged.

The subsequent natural failure on Item/Source 26535 (`13590:670650`,
第156話 (1) of 暁のヨナ) supplied the missing wait-time evidence. Metrics
`e0d1d5f9b15c49099c452c183f35db4c` show 41 completions then this failure,
without 403/429/5xx/challenge/CAPTCHA/retry. After saving p1, the approved
p1-to-p2 wait recorded three samples at 12.434, 132.279 and 241.975 ms.
Each had active p2, loaded/visible 764x1200 canvas at [-204, 0, 764, 1200],
frame [570, 0, 764, 1200], viewport [1904, 1200, 1], and `inFrame=false`.
Stability counts were 1, 2 and 3; the geometry error propagated at 242.033 ms.
The backing size, viewport/DPR and reader mode match supported conditions.
The confirmed stopping mechanism is counting unchanged off-frame geometry as
ready, then rejecting it, before the existing 10-second wait expires. These
records do not prove when or whether this particular p2 later settled, and do
not retrospectively establish the exact cause of Item 26357's older failure.
The failure-time diagnostic is retained in
`output/batch/piccoma/item-26535-source-26535-20261014T133029724521+0900-d58f4e1a070247819ddb64f113f4796b/diagnostics/metadata.json`.
The initial investigation changed documentation only. The subsequent
implementation extends bounded in-frame readiness to ordinary-size pages as
described above; the geometry/capture gates have not been relaxed.

On an exception from body readiness, `collect_debug_metadata()` now exposes
`piccoma_body_wait_failure`, written through the existing Core diagnostics path
to `diagnostics/metadata.json` under
`adapter_debug.piccoma_body_wait_failure`. It records the requested page ID,
expected cursor at wait entry, preceding advance, exception type/message,
elapsed time, total sample count, the first sample and the last eight samples.
Samples reuse the existing reader snapshot: elapsed time, current page IDs,
viewport/DPR, frame rectangle, reader-mode counts and the requested/active
page rows with backing/display dimensions, loaded/in-frame flags, ancestor
visibility and consecutive stability count. No extra browser RPC, screenshot,
source response read, raw JPEG, signed source URL or authentication field is
added. A later settled diagnostics screenshot cannot replace these retained
failure-time values. Successful waits expose no new debug field; a new wait
clears the previous failure record. There is no new configuration or CLI flag.

Current synthetic browser regressions cover bounded ordinary/scaled waits,
settle the page after failure, verify the retained geometry reaches actual
metadata.json unchanged, check bounded sample retention and record clearing,
and verify exactly one next click. The diagnostic implementation captured the
natural Item 26535 failure described above. Core implementation is unchanged,
so `note/00_core.md` does not require synchronization. Local evidence is ignored
under `work/piccoma/26357-readiness-20261014/`.

Validation: the focused diagnostics/readiness selection passed 9 tests; the
final affected native-capture Unit and adapter browser Integration selection
passed 493 tests, 0 failed, 0 skipped (249.24s; five existing asyncio warnings).
Global Ruff and scoped diff checks passed. Packaging, Discovery/Policy,
separate Research and full-repository suites were not rerun because their
contracts did not change. No additional live failure verification was run
after this diagnostics-only change; synthetic tests exercise the retained
failure record through the existing diagnostics writer.
The initial Item 26535 investigation ran no new tests or live probes: it inspected
the recorded failure and unchanged readiness code, and updated documentation.

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

## Current adapter and CLI registration

Phase 07 Stage A and Stage B passed independent review. The distributed `crawler.yaml` sets `sites.piccoma.page_turn_delay_ms: 200`, `inter_candidate_delay_ms: 3000`, and the existing fail-stop flags to true. Manual CLI and Batch use the shared runtime-settings loader and pass the resolved page delay into `RunConfig`; the common 1,000ms fallback and other site values are unchanged. Explicit zero remains valid. Stage B transports the same full native trace as JSON at all six existing checkpoints and restores dicts for existing validators/signatures. Intentional nulls are preserved; unsupported values, malformed/ambiguous JSON, negative zero, schema errors, and payloads above 8 MiB fail closed as unknown target continuity. The 8 MiB cap is a new full-trace transport bound derived as 512 events × 16 KiB/event, with an independent 512 × 256-node traversal bound; it never truncates traces. The existing finite DPR tolerance `1e-7` and raw viewport before/after equality are retained. Stage C compared object and JSON at the same YAML 200ms setting in four interleaved 12-page manual runs: all 48 corresponding WebP files were byte-identical, native-only, and fallback-free. Mean normal cycle fell from 3.601s to 2.743s (0.857s, 23.8%); the six trace RPCs fell by 0.864s and JSON decode added 0.034s. A separate 24-page Batch reached explicit END and passed ZIP/Catalog checks; a fresh prepackage audit then independently verified all 24 manifest entries and 144 native evaluations / 144 JSON decodes. The final Stage C Reviewer review passed with BLOCKING 0. WebP remains lossless method6; no PNG/trace-count/stability/thread refactor is included. The separate [genre correction plan](../research/piccoma-performance/GENRE_FIX_PLAN.md) remains unimplemented and requires verified product-type evidence.

`PiccomaDiscoveryAdapter` is registered with Discovery. `PiccomaAdapter` is registered in the manual crawl and Batch adapter registries, and `PiccomaSitePolicy` is registered with the generic Batch Planner. Entry supports only `auto` and `direct`, both freshly verifying exact-free or already active manual-unlock access. Batch includes available free sources and available quota sources with a future observed manual-grant bound, always as non-consuming `direct`. Quota sources without an active grant and paid/owned/grant/rental/unknown/unavailable states are excluded. No automatic access acquisition is implemented.

The adapter uses the existing BrowserSession/CDP lifecycle and receives an owned Playwright Page. It does not launch Chrome, resolve endpoints, connect over CDP, or read/write Catalog directly. The generic Discovery service remains the Catalog writer. No Core, shared schema, or shared runtime changes were made for Piccoma.

## Discovery contract

The Watchlist URL must be a canonical HTTPS viewer URL:

```text
https://piccoma.com/web/viewer/{product_id}/{episode_id}
```

Discovery derives the matching product episode listing URL and buffers the complete listing before yielding records. It validates the final HTTPS origin/path, product heading, declared total, exact row count, product and episode IDs, uniqueness, title/status presence, target membership, and supported DOM ordering. An incomplete or contradictory listing fails before the adapter yields any records.

The native listing is oldest-to-newest (`#js_episodeList.PCM-list_asc`); Discovery emits canonical latest-to-oldest order. Global position is `original_dom_index + 1`, assigned before inclusive bounded slicing. Source identity is the safe composite `product_id:episode_id`; URL IDs are authoritative and `work_key` remains opaque caller metadata. Existing Discovery service behavior owns full/incremental refresh, Catalog writes, and completed Item retention.

## Access classification

Status markers are collected from both `.PCM-epList_status` and its descendants. Free requires the exact marker set `PCM-epList_status_free` and exact visible `¥0`. A conflicting wait/point/other prefixed marker produces unknown. Observed wait-free is quota; a positive integer point price is paid; ambiguous or missing evidence is unknown. The generic wrapper label, `data-user_access`, and personal readability do not prove unconditional free access.

Manual unlock evidence is the sole prefixed marker `PCM-epList_status_waitfreeRead` with normalized text `閲覧期限 残りN時間`, where N is a positive integer of at most three digits. It maps to quota, never free. Discovery records `access_granted_until = observation_start + (N-1) hours` and `access_checked_at = observation_start`; `free_until` stays null. Display rounding is unverified, so one hour is reserved. This is a conservative eligibility bound, not an exact expiry. One-hour countdowns are not future grants. Zero/minutes/other forms and contradictory markers establish no grant; every validated row explicitly clears previous grants when valid evidence disappears.

Piccoma's incremental stop hook continues through every row in the requested scope because old episodes can be manually unlocked after discovery. The full DOM listing is already buffered, so no extra listing request is added. Incremental still does not mark unseen rows unavailable. Both modes refresh grants and `access_checked_at`, retaining completed Items and artifacts.

At viewer initialization, the adapter refreshes the product listing and requires the unique composite row to be exact-free or to carry a valid manual-unlock badge with a future conservative bound. Catalog timestamps alone never authorize entry. The canonical viewer request must return HTTP 200 and the same product/episode identity; the observed `/web/viewer/s/{product}/{episode}` redirect is accepted only with fresh manual-grant evidence. The exact accepted URL is bound for all subsequent reader/capture checks, while Catalog/manifest source URLs stay canonical. Missing/expired grants, paid/unknown state, foreign redirects, duplicate/missing rows, and unexpected dialogs fail closed. No ticket/point/coin/waiting/purchase/unlock activation is performed.

On the 2026-10-09 snapshot, product 28600 exposed 432/432 exact-free rows. Product 28606 exposed 12 exact-free rows, 167 wait/binge-free rows, and 39 point-priced rows. These are observations, not constants. Seeds 28600/1910027, 28600/4142286, and 28606/2001009 appeared at native DOM indices 0, 421, and 1 respectively.

## Batch policy

The policy admits available free sources as `direct` (`free`), and available quota sources with an aware `access_granted_until > now` as `direct` (`active_manual_grant`). Both have `consumes_quota=False` and no resource. Missing/expired grants are rejected (`no_active_manual_grant`), malformed/naive timestamps raise SitePolicyError, and paid/owned/grant/rental/unknown states remain unsupported. Piccoma declares no access resource, resource pass, or grant-only resource. Catalog ordering, composite identity, display-position prefix, and Work/Item metadata remain generic Planner responsibilities.

The standard `BatchExecutor` revalidates Catalog state. Before viewer entry, `PiccomaAdapter` independently checks fresh free/manual-grant evidence and matching composite identity. It does not consume a resource or fall back to acquisition. Existing normal `discover` and `batch run` commands need no new flags; rerun Discover after manually unlocking episodes. Completed Items stay excluded by the generic Planner.

### Manual-unlock live verification (2026-10-10)

The user requested manual ticket unlocks to be discovered and included in
normal Batch. In the shared Chrome profile, product 28600's full episode page
had 432 rows, including 32 with the exact `waitfreeRead` marker and
`閲覧期限 残り71時間`. No exact expiry attribute was exposed. The separate product
page showed only five preview rows, so Discovery continues using `/episodes`.
This snapshot classified 31 free, 357 quota (including the 32 observed grants),
and 44 unknown. Counts are observations, not policy constants.

Using a dedicated ignored Catalog, both full and subsequent incremental
Discovery exhausted all 432 rows. Incremental had 432 known and zero new rows;
all 32 grants were recorded and selected as non-consuming `direct` candidates.
The plan had 63 candidates total: 31 free and 32 manual grants.

The first bounded Batch attempt safely stopped before capture because the
site redirected the unlocked episode to `/web/viewer/s/28600/1910236`. A bounded
probe confirmed that both canonical navigation and clicking only the already
unlocked row reach that same reader, HTTP 200, with one viewer root and no
activation dialog. Production now admits this route only after fresh grant
evidence and binds the exact accepted URL for subsequent operations.

After that correction, the standard Planner/BatchExecutor/Runner/packager path
for 28600:1910236 reached explicit END and completed the dedicated Item.
All 22 ordered `page-0001.webp` through `page-0022.webp` members passed ZIP CRC,
full image decode, unique hashes, single-frame 844x1200 WebP, and VP8L lossless
header checks. Archive size was 13,911,838 bytes. Pages p1/p12/p22 were visually
inspected for intact body content without viewer UI. No AccessGuard events
were observed; `quota_started_at` stayed null, the observed grant stayed
unchanged, and no ticket/point/purchase activation control was clicked. The
normal Catalog, Watchlist, and library were not changed by these probes.

Sanitized evidence is ignored local output under
`output/piccoma_manual_grants/`: `listing_evidence.json`, `entry_evidence.json`,
and `verify-20261010T120947Z-a13cd4/evidence.json`. Full-size image/ZIP artifacts
remain local ignored output. Other countdown units, exact expiry rounding,
other reader layouts, and automatic ticket acquisition remain unverified or
unsupported. A grant near expiry may be excluded earlier than the site;
rediscovering cannot establish a future bound from a one-hour/minute display.

The final targeted/affected run passed 166 tests, 0 skipped: Piccoma Discovery
and Policy Unit files plus both Piccoma browser Integration files. The shared
Discovery/Batch Planner/BatchExecutor boundary run passed another 137 tests,
0 skipped. Ruff (`ruff check src tests`) and `git diff --check` passed. Existing
pytest-asyncio deprecation warnings remain (9 and 874 respectively). Synthetic
redirect fixtures now expose final URLs through same-origin history replacement
instead of fulfilled 302 responses, whose follow-ups escape Playwright routing;
these tests no longer depend on the live sign-in/site response. Real HTTP
redirect behavior is evidenced by the bounded live checks above.

This request changed `site_adapters/piccoma/discovery.py`, `adapter.py`,
`site_policies/piccoma.py`, `tests/unit/test_piccoma_discovery.py`,
`test_piccoma_policy.py`, `tests/integration/test_piccoma_discovery_browser.py`,
`test_piccoma_adapter_browser.py`, `docs/DISCOVERY_AND_BATCH.md`, the Piccoma
README, and this note. Shared production Core/Batch/Catalog code was unchanged,
so `00_core.md` needed no change. The full repository suite and unrelated
Research/Probe tests were not rerun for this site-local extension; relevant
Unit, browser Integration, shared boundary tests, and live verification ran.

## Viewer state and navigation

The live-supported layout has root `#react_ViewerApp`, body classes `PCM-stt_horizontal` and `PCM-prop_scroll_l`. The page list is `#react_PageListApp`; its frame is `#js_frame.PCM-viewer2_frame`. Body wrappers have unique contiguous IDs `p1..pN` followed by one `last` wrapper. The observed page sequence was p1 through pN via the in-episode next control; native DOM wrapper order is reversed. These facts do not infer additional semantics from the `PCM-prop_scroll_l` class. Unknown layouts, missing IDs, duplicates, and non-contiguous page sets fail closed.

A body page is considered loaded only when its expected ID is the sole active page, the page has exactly one canvas and one loaded canvas wrapper, the canvas and every ancestor are displayed and visible with opacity 1 and content-visibility visible, and canvas viewport/backing geometry remains stable over three samples. After p1 normalization, the expected cursor advances only after the adapter uses the in-episode next control and verifies the exact next page ID. Unrequested jumps and rewinds are UNKNOWN. END is valid only after advancing from pN to active `last` with `#js_viewerEnd`; no next-episode control is clicked.

On entry, after a bounded 1.5-second attachment grace, the adapter automatically clicks `キャンセル` on the unique observed resume dialog after validating its exact prompt shape/text, two expected enabled buttons, and lack of links. It waits for the dialog to close, normalizes the reader to p1 if necessary, and verifies a loaded, stable first-page canvas before capture can start. It never selects `移動する` to continue from the persisted reading position. Besides the numeric-page wording, the exact observed last-page wording is `前回最後のページを 読んでいました。 最後のページに移動しますか？`; mixed numeric/last-page wording or extra text is rejected. A different or ambiguous dialog aborts. The unique #js_scrollTypeSing reading-direction guide is hidden during capture only after validating one of the two observed exact root class sets (base class alone, or base plus `_sh` and `_show`), the same two child groups, three expected image labels/classes, lack of meaningful text/interactive nodes, and empty pseudo-element content; its original inline style and visible state are restored. Unknown or duplicate guide markup aborts.

On 2026-10-10 this existing behavior was verified on the user-specified
6913:2770415 viewer with the shared Chrome profile and freshly checked free
entry. The first probe observed and canceled the persisted last-page prompt,
then initialized at p1. After advancing only to p2 and closing the owned Page,
reopening showed `前回2ページを読んでいました。 2ページに移動しますか？`.
The unchanged adapter canceled it, observed zero remaining dialogs, initialized
at p1, and successfully captured p1 as 764x1200 native lossless WebP. This was
rechecked in a second bounded reopen probe. Source image bytes were not saved
by these probes, Catalog was unchanged, and no entitlement action was taken.
Sanitized evidence is local ignored output at
`output/piccoma_resume_investigation/before_fix.json` and `verified.json` (the
first filename labels the initial investigation; no production fix was needed).
The existing resume/first-page/unknown-dialog browser tests passed 8 tests,
0 skipped, 57 deselected, with 5 existing pytest-asyncio deprecation warnings.
No production or test code was changed for this verification; unrelated tests
and the full suite were not repeated.

## Capture path and provenance

Before navigation, the owned Page viewport is set to 1904x1200, the observed supported layout. Before and after each capture the adapter verifies the same viewer identity, expected page cursor, active page ID, loaded canvas, computed display/visibility/opacity/content-visibility on the canvas and every ancestor, frame/canvas geometry, viewport, and output dimensions. A hidden or translucent canvas, cursor change, geometry change, or identity change fails closed without entering an unverified Core fallback.

Phase 07 Stage B serializes the same full trace at all six existing fresh snapshot checkpoints and restores it as a dict for the existing validators/signatures. Browser-side preflight rejects unsupported values before JSON can omit/coerce them; Python rejects malformed JSON, duplicate keys, invalid root schema/types, negative zero, and payloads beyond the fail-closed 8 MiB / 131,072-node budget. Intentional nulls survive. A transport/schema error means target continuity is unknown and becomes `UnknownPageStateError`, including at the internal post-replay/post-encode, Adapter outer, and final-current checkpoints. It cannot trigger a Core fallback without proof. Call timing/count, encode-after freshness, source/provenance gates, output pixels/codec, and DPR checks remain unchanged. Independent Stage B review passed. Stage C's four-run manual comparison, 24-page Batch END/ZIP/Catalog checks, and fresh per-page manifest audit passed; the final Stage C Reviewer review passed with BLOCKING 0. Evidence and exact scope are linked in the Phase 07 research reports.

Live canvas `getImageData` raised `SecurityError`, so direct canvas readback remains unavailable. The 1:1 native horizontal rendering profiles use backing widths 764, 842, or 844 and height 1200 (the separate 1125x1600 and 1350x1920 scaled RGBA profiles are described above), and require one loaded HTML image bound to one unique exact first-party JPEG response and stable load generation. Width 764 uses the observed 16-column / 24-row grid with 384 draws; widths 842/844 retain the 17-column / 24-row grid with 408 draws. Each accepted trace requires exactly three setup events plus that grid's draw count, complete unique source and destination grids, and the unchanged source/context/generation checks. Replay output must report the validated trace's exact draw count. Other stable canvas sizes can reach the Core PNG fallback but are not native-replay supported. The adapter records complete draw arguments and supported 2D context state without changing the page renderer. It replays the exact fractional source/destination rectangles and state into a detached canvas using the browser's normal image decoder, then composites the transparent replay over a separately validated solid-white paint ancestor. The 1200px-high profiles encode these verified RGB pixels as lossless WebP; the two enumerated scaled profiles preserve RGBA in lossless WebP without white compositing. Acceptance requires one simple VP8L chunk, the expected decoded dimensions, and exact equality of every RGB byte. It does not save tiled JPEG bytes as a page or change canvas security/backing settings. If WebP encoding or proof fails, the already verified native result remains PNG with a sanitized encoding-fallback reason. If native attribution/replay proof is unavailable before materialization, Core canvas/Locator capture remains PNG and requires an unchanged target generation.

### 764px native support and remaining PNG fallback limit (2026-10-10)

The ordinary Batch for item/source 24649, product/episode 6913:2770415
(FINAL TURN 夢), stopped on p1 with zero saved pages. Its diagnostics record
`core_canvas_or_locator_png` and native fallback reason
`target_canvas_identity_or_dimensions`. A bounded live investigation freshly
verified exact-free entry through the unchanged adapter and reproduced the same
failure on p1 only: backing dimensions were 764x1200, canvas rect was
`[569.6666870117188, 0, 764, 1200]`, and DPR was
`1.0000000298023224`. Canvas `toDataURL('image/png')` raised `SecurityError`;
the existing Locator screenshot path returned a valid, fully decoded PNG at
765x1200. The adapter requires the result to match the 764x1200 backing size
exactly and therefore raises the combined format/dimensions error. This is an
unsupported native size followed by a screenshot clipping/dimension mismatch,
not an observed corrupt PNG or WebP encoder failure.

An isolated synthetic page in the same shared Chrome reproduced the clipping
boundary: a 764x1200 canvas at integer x=570 yielded 764x1200, while x=569.666687
and x=569.5 each yielded 765x1200. A subsequent bounded live trace probe checked
all p1..p20 and explicit END: every page had the same 764x1200 backing size,
387 events including 384 draws, complete source and destination grids, one
source object, and a validated white backdrop. Production therefore adds only
this observed 764px grid to native replay; it does not change Core, widen output
dimension tolerance, resize/crop output, or change screenshot fallback geometry.
Unknown widths remain unsupported. If native proof is unavailable and Locator
rounding changes the fallback dimensions, the strict check still stops safely;
this remaining fallback limitation is not claimed fixed.

The unchanged manual CLI then freshly verified free entry and saved all 20
pages through explicit END and the normal packager, using isolated output and
library directories. ZIP CRC, ordered `page-0001.webp` through `page-0020.webp`,
20 unique hashes, and full decode / single-frame lossless VP8L validation at
764x1200 all passed. All members are native WebP, with no PNG fallback. Pages
p1/p10/p20 were also visually inspected for intact body content and absence of
viewer UI. Packaging removed its generated source directory normally and
recorded a completed crawl-status file; no Catalog completion is claimed.
The original failed Batch and Catalog were not modified, and no paid/quota
resource was used. The original Batch had 18 completed candidates and no
recorded HTTP 403/429/5xx or CAPTCHA/challenge signals.

The affected native-capture Unit and full Piccoma adapter browser Integration
suite passed 163 tests, 0 skipped, with 5 existing pytest-asyncio deprecation
warnings. Regression coverage includes pixel-identical synthetic native output
at all three supported widths, the 764px fractional-position / 765px Locator
case, duplicate source/destination tiles and unsafe traces, and rejection of
unobserved widths. `ruff check src tests` and `git diff --check` passed. The full
repository suite and unrelated Research tests were not run for this site-local
change. Sanitized evidence and bounded probe/audit scripts are ignored local
artifacts under `output/piccoma_investigation_24649/`; the completed ZIP and QA
images remain local ignored output, with no copyrighted payloads or signed URLs
committed.

The Phase 06-C coefficient feasibility probe confirmed that the exact observed JPEG response can be read by `jpeglib.read_dct`, but the unchanged Jump+ `dct_lossless_feasibility` helper rejects the actual Piccoma rectangles as `tile_geometry_not_mcu_aligned`. The 408-draw trace contains 50-pixel destination tiles, 44/42-pixel edge tiles, source-height `50.01`, destination-height `50`, and recorded image smoothing enabled at quality `low`; the fractional geometry was passed through unchanged. The observed source is baseline 8-bit, three-component 4:4:4 with 8x8 MCUs. The existing Jump+/Magapoke coefficient transform requires integer, equal-size, MCU-aligned rectangles, which this mapping does not provide. This rules out applying that existing coefficient-permutation method to the observed path; it does not claim every possible custom JPEG transform is impossible. The equal-50-height seam/phase analysis in the sanitized report is diagnostic only and is never used to round production geometry. Phase 06-D keeps faithful browser replay and emits lossless WebP from its verified RGB pixels.

The trace and response registry are bounded. Per-canvas dimension MutationObservers are attached only to retained source candidates or the current capture target and are disconnected on eviction/capture cleanup; this also detects same-value NamedNodeMap changes while a canvas is detached. Missing/ambiguous responses, source reloads, canvas reset or unsupported paint/clip/state operations, overflow, unproven backdrop, or replay mismatch make the optimization unavailable. White compositing requires computed `background-clip:border-box`, `clip:auto`, no border widths/radius, and the other validated covering-white paint conditions. Core `capture_locator` is then allowed only when the active target canvas generation stayed unchanged for the entire capture; target mutation during any path fails closed. Successful default native output reports `native_tile_replay_lossless_webp`, `source_native=true`, `source_mime=image/jpeg`, `output_format=image/webp`, `output_lossless=true`, and `source_backdrop=verified_solid_white`. Native PNG fallback reports `native_tile_replay_png` plus an encoding-fallback reason. Core screenshot fallback reports `source_native=false`, PNG output, and a sanitized proof-fallback reason; a WebP result cannot be accepted under Core PNG metadata. Output validation fully decodes files, rejects animation/multiple frames, and checks MIME, extension, and bytes. No signed URL, source bytes, or response body enters metadata.

## Live verification and artifacts

The `NamedNodeMap` trace wrappers preserve the browser API contract by forwarding every argument to the native method and returning its native result. A synthetic browser regression confirms two-argument `removeNamedItemNS(namespace, localName)` behavior on a non-canvas `div`; canvas dimension invalidation remains owned by the bounded per-canvas observer.

On 2026-10-09, after the Reviewer fixes, each seed was rechecked as exact-free in its current listing, entered at the requested viewer path, traversed from p1 through every page to explicit active END, and captured at first/middle/last. Product 28600/1910027 had 24 body pages and captures p1/p12/p24 (844x1200). Product 28606/2001009 had 15 body pages and captures p1/p8/p15 (842x1200). Both viewer paths were unchanged at END. The reading guide was visible before and after all six captures. All six latest ignored PNGs were visually inspected; the body filled the frame sharply without reader chrome. The Lead also inspected product 28600 p1.

Phase 01 evidence files are sanitized metadata only and contain no image payloads. The Phase 03 rendered QA PNGs remain local ignored artifacts in `output/piccoma_experiment/`; their summary is `phase03_b_live_capture_evidence.json`. No image payloads, browser state, cookies, or signed URLs are committed.

## Tests and remaining scope

Phase 02 independent review: 60 passed, 0 skipped, BLOCKING 0. Phase 03 independent review: PASS, BLOCKING 0, 174 passed, 0 skipped. The focused implementation run also passed 174 tests with 288 pytest-asyncio event-loop-policy deprecation warnings. `ruff check src tests` passed. Browser-fixture tests cover entry and identity guards, delayed/exact/unknown dialog handling, complete/partial/duplicate readiness, transitions, unapproved jump/rewind rejection, END, guide restoration, canvas/ancestor visibility before and after capture, geometry, and capture format/dimensions/payload; guide checks reject appended text and unknown elements.

A local synthetic-browser Batch integration test exercises Planner -> BatchExecutor -> Runner -> Piccoma adapter -> Manifest -> ZIP -> Catalog completion for a three-page episode. Stale-free listing, wrong composite candidate identity, and redirected viewer failures create no ZIP, completed Item, or Artifact and do not mutate quota/resource state. Phase 04 local policy/CLI tests passed (96 passed, 0 skipped), its browser Batch integration passed (34 passed, 0 skipped), and the combined affected suite passed (310 passed, 743 pytest-asyncio event-loop-policy deprecation warnings, 0 skipped); `ruff check src tests` passed. Independent Phase 04 review passed with BLOCKING 0 (130 passed, 0 skipped).

On the 2026-10-09 Phase 05 run, full Discovery returned 432/432 records for product 28600 and 218/218 for product 28606. Incremental Discovery observed five known records per product, added none, and stopped at the generic `known_streak`. The read-only Batch plan had 444 free/available direct candidates and skipped 206 non-free candidates (`unsupported_access_mode`); there were zero quota-resource rows. These counts are a run snapshot, not constants.

The independent Tester ran the real `BatchExecutor -> CrawlerRunner -> package_crawl_output -> Catalog finalize` path for 28600/1910027 (24 pages, 844x1200 PNG) and 28606/2001009 (15 pages, 842x1200 PNG). Each stayed on the requested viewer path, reached explicit END, and produced contiguous unique IDs, exactly matching ZIP/Manifest members, passing CRC and image-hash checks, a matching Catalog ZIP Artifact, a completed Item and a succeeded Run. First/middle/last images for both were visually checked. There were no ticket or entitlement actions and no quota state rows. Tester evidence is under ignored `output/piccoma_experiment/phase05_tester/evidence/`.

The live listing was freshly checked before viewer entry; both resulting Sources remained `available=true` and `access_mode=free`, with quota/grant timestamps NULL and no quota resource rows. `last_seen_at` was populated, but Catalog `access_checked_at` remained NULL; live free revalidation is therefore evidenced by the run, not represented by that Catalog timestamp. Windows PowerShell redirection/piping of the planner output failed once under cp932 on title code point U+8E20. The command passed with task-local `PYTHONIOENCODING=utf-8` and `PYTHONUTF8=1`; no lossy title conversion or shared CLI change was made.

The accepted viewer layout remains horizontal at 1904x1200. Historical Phase 06-B selected live checks used exact DPR 1 for both products and native replay at p1/middle/last: product 28600 pages p1/p12/p24 were 844x1200; product 28606 p1/p8/p15 were 842x1200. All six reconstructed PNGs were pixel-identical in RGB to the unchanged Locator screenshot path; both episodes reached explicit END on the same viewer URL. A later shared-CDP diagnostic observed `devicePixelRatio=1.0000000298023224` at the same viewport; the former exact comparison rejected that floating-point result before normal capture. The adapter now accepts only finite numeric DPR values with `abs(DPR - 1) <= 1e-7`; booleans, non-finite values, and ordinary scaled modes such as 1.25 or 2 remain unsupported. The raw `[innerWidth, innerHeight, devicePixelRatio]` array must be identical before and after each capture, so a DPR change within the tolerance during materialization still fails closed. The existing canvas dimensions, frame bounds, visibility, backing size, source identity, draw trace, backdrop, target-generation and output checks are unchanged. In a bounded live measurement using the shared Chrome through CDP, two 12-page runs accepted the observed near-1 DPR and each captured p1..p12 with `native_tile_replay_lossless_webp`, 24/24 total and zero fallback. The run stopped at its configured page bound before END, so it does not replace the historical Phase 06-D full-episode END verification. Across 20 completed steady-page cycles (capture start pN to capture start pN+1), wall time was mean 4.538 s, median 4.151 s, p90 5.627 s, maximum 5.772 s; p1 cycles were 5.571 s and 5.398 s. Existing 1,000 ms pacing and method-6 lossless WebP remained enabled. Detailed stage timings, overlap rules and unmeasured limits are in [the performance profile](../research/piccoma-performance/PROFILE.md#full-current-pipeline-live-profile-handoff-two-runs). Both runs used isolated owned contexts and outputs; Catalog and normal outputs were unchanged, with no paid or quota resource. These checks establish the current DPR gate and bounded capture path for this setup, not other layouts, draw graphs, backdrop structures, or resources. Detached-canvas attribute-reset and `background-clip:text` rejection cases remain synthetic browser regressions, not additional observed site variants. The Phase 05 full suite result was 1827 passed, 0 skipped. For Phase 06-B, the focused Piccoma/affected native-capture suite passed 249 tests with 306 existing pytest-asyncio deprecation warnings and 0 skipped; `ruff check src tests` passed. The final full Phase 06-B suite passed on the checkpoint immediately before the last NamedNodeMap compatibility fix: 1881 passed, 3558 warnings, 0 skipped in 353.38 seconds. The final compatibility fix was covered separately by its focused browser test and final Reviewer pass.

The final API compatibility check passed 1 browser test (48 deselected, 0 skipped, five existing pytest-asyncio warnings). It compares the native and hooked `removeNamedItemNS(namespace, localName)` result and confirms the attribute is removed from a non-canvas element. Final independent Reviewer review passed with BLOCKING 0.

Phase 06-B historical PNG verification commands:

```text
.venv/Scripts/pytest.exe -q tests/unit/test_piccoma_native_capture.py tests/integration/test_piccoma_adapter_browser.py -k "detached_named_map or background_clip_text or white_backdrop_gate"
16 passed, 72 deselected, 5 pytest-asyncio warnings

.venv/Scripts/pytest.exe -q tests/unit/test_piccoma_native_capture.py tests/unit/test_piccoma_discovery.py tests/unit/test_piccoma_policy.py tests/integration/test_piccoma_discovery_browser.py tests/integration/test_piccoma_adapter_browser.py tests/unit/test_comicdays_native_capture.py tests/unit/test_bookwalker_native_capture.py
249 passed, 306 pytest-asyncio warnings, 0 skipped
```

`git diff --check` and the explicit new-file EOF/trailing-whitespace check passed. The final independent Reviewer gate is PASS, BLOCKING 0. The full suite result was run on the immediately preceding checkpoint; the final compatibility patch was verified separately rather than included in that full run.

## Phase 06 historical independent live E2E under PNG output contract

The independent Tester report is at ignored `output/piccoma_experiment/phase06_tester/runs/20261009T053043Z-08fcc951/evidence/phase06_tester_report.json`. Full Discovery exhausted 432/432 rows for product 28600 and 218/218 for 28606. Incremental Discovery observed five known rows per product, added none, and stopped at `known_streak`. The read-only plan had 444 eligible/direct candidates, 206 skipped non-free candidates, and zero quota candidates. These counts describe that run, not constants.

| Product/episode | Body pages | Result |
| --- | ---: | --- |
| 28600/1910027 | 24 at 844x1200 PNG | ordered unique pages, all `native_tile_replay_png`, explicit END, succeeded Run, completed Item, ZIP Artifact present |
| 28606/2001009 | 15 at 842x1200 PNG | ordered unique pages, all `native_tile_replay_png`, explicit END, succeeded Run, completed Item, ZIP Artifact present |

All 39 pages used `source_native=true`, JPEG source MIME, verified solid-white backdrop, and no fallback. The exact ZIP members matched the Manifest and passed CRC/member-hash checks; all image hashes were distinct within each episode, and Catalog Artifact checks passed. Six current first/middle/last same-page RGB comparisons and six visual checks passed. Sources remained available/free; quota/grant fields did not change and quota resource rows stayed at zero. Both viewers remained at their requested URLs through END. No paid or entitlement action was used. The Reviewer independently rechecked the actual ZIPs against the Manifest and read-only Catalog data and verified the six current image comparisons: PASS, BLOCKING 0.

## Phase 06-C JPEG coefficient feasibility probe (2026-10-09)

The bounded probe checked only p1 for 28600/1910027 and 28606/2001009, after a fresh exact-free listing check and composite target identity validation. Each production trace was complete with 408 draws and one uniquely matched, observed `image/jpeg` response (1,951,370 bytes and 789,375 bytes respectively). The bytes were read once from the normal observed response; `jpeglib.read_dct` succeeded, and each temporary JPEG file was deleted. No raw source URL, response bytes, or image payload was persisted. The probe made zero forward-page and entitlement actions, then closed its Pages and CDP session. The independent evidence/design review passed with BLOCKING 0. Sanitized evidence is ignored at `output/piccoma_experiment/source_capture_research/phase06c_jpeglib_p1_evidence.json`.

Both sources were baseline 8-bit, three-component 4:4:4 JPEGs with 8x8 MCUs. The observed 408-draw geometry had 50-pixel body tiles plus 44-pixel (28600) or 42-pixel (28606) edge widths; source crop height was exactly `50.01`, destination height `50`, and observed image smoothing was enabled with quality `low`. The unmodified Jump+ `dct_lossless_feasibility` helper received the original fractional rectangles and rejected both as `tile_geometry_not_mcu_aligned`. This is evidence that the existing integer/equal-size/8x8-aligned Jump+/Magapoke coefficient-permutation method does not support this observed path. It is not a claim that every possible custom JPEG transform is impossible.

The report's equal-50-height seam/phase and 4x4 grouping analysis is explicitly diagnostic only. It does not normalize, round, or alter any production rectangle. The observed first destination 8x8 block begins at source phase (6,6) for 28600 and (6,2) for 28606 and touches multiple source DCT blocks; none of 24 central 4x4 groups was a contiguous translated source group in either trace. At the Phase 06-C checkpoint, output was the verified reconstructed/composited PNG; Phase 06-D later adds lossless WebP encoding without changing replay geometry. Probe script `py_compile` and Ruff passed; no tests or full suite were rerun for this research/docs-only update. Independent evidence/design review: PASS, BLOCKING 0.

## Phase 06-D lossless WebP implementation

The native replay contract through exact JPEG response attribution, the 408
fractional canvas draws, and proven-white RGB composition is unchanged. The
default result encodes those RGB pixels as lossless WebP (`lossless=True`,
`method=6`). Validation requires a single `VP8L` chunk with exact RIFF/chunk
lengths and expected encoded dimensions, full file verification/decode, one
frame, MIME/extension agreement, and byte-for-byte equality of every decoded
RGB channel with the verified composited pixels. A pixel-identical 1x1 lossy
WebP still fails because its payload is `VP8 ` rather than `VP8L`. If the
WebP encoder or RGB verification fails, the same verified native pixels remain
PNG with `encoding_fallback_reason`; if source proof is unavailable, the Core
path remains PNG. A Core PNG capture cannot be accepted as WebP under PNG
method metadata. The target generation is checked after encoding, so a reset
during encoding fails closed.

The standard local three-page Batch integration verifies WebP page suffixes,
Manifest MIME/extensions, decoded dimensions, ZIP member names and image
payloads through the normal packager and Catalog completion path. A three-page
regression tests native PNG on p1 after encoder failure, Core PNG on p2 after a
synthetic unsupported canvas operation, native WebP on p3, and metadata clearing
after a failed cursor-state capture. The Phase 06-D code Reviewer and independent
live Tester passed with BLOCKING 0.

The isolated live Tester report is ignored at
`output/piccoma_experiment/phase06d_tester/runs/20261009T073152Z-3e91e9e0/evidence/phase06_tester_report.json`.
Full Discovery exhausted 432 rows for 28600 and 218 for 28606; incremental mode
saw five known rows per product and stopped at `known_streak`. The read-only plan
had 444 direct eligible candidates, 206 skipped non-free candidates, and zero
quota candidates. In the standard Batch-to-ZIP path, 28600/1910027 produced 24
pages at 844x1200 and 28606/2001009 produced 15 at 842x1200. All 39 pages used
the validated lossless-WebP native method without fallback. Ordered IDs, unique
per-episode hashes, exact ZIP/Manifest membership, CRC/member hashes, Artifact
hash/size, completed Items, succeeded END Runs, and present Artifacts passed.
Six current same-page comparisons with unchanged Core capture (p1/p13/p24 and
p1/p8/p15) had zero RGB differences and passed visual inspection. The prior
39-page PNG RGB comparison is secondary historical evidence. No access-right
fields changed, quota resource rows stayed 0 before/after, and no entitlement
action occurred.

For these 39 pages only, observed JPEG response bytes totaled 37,346,355 and
WebP output totaled 25,356,052 (-32.11%). By product, 28600 measured 26,159,334
to 18,055,076 bytes (-30.98%), and 28606 measured 11,187,021 to 7,300,976
(-34.74%). All WebP pages were smaller than their observed source body in this
run; this is not a general size guarantee. Downstream WebP reader compatibility
outside the tested browser/Pillow/ZIP path was not separately verified. No image
bytes, signed URLs, or credentials are recorded in Git.
