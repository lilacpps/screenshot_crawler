# Piccoma adapter

## Implemented scope

Piccoma Discovery and the horizontal viewer/Capture adapter support unconditional free access and already active manual unlocks. Discovery validates complete product episode lists and records observed manual-unlock expiry separately from free access. The viewer adapter rechecks the target's current listing state before entry. The 1200px-high profiles first attempt the strictly proven, site-local JPEG tile replay and white composite, then encodes those RGB pixels as validated lossless WebP. If WebP encoding or exact round-trip proof fails, it retains the same verified native pixels as PNG with an encoding-fallback reason. If source attribution is unavailable before materialization, it uses the existing Core canvas/Locator PNG path.

The 1200px-high native profiles support the live-observed 764x1200 grid (16 columns, 384 draws)
and the existing 842/844x1200 grids (17 columns, 408 draws). Each trace must
contain the exact setup/draw count and complete unique source/destination grids;
source attribution, fractional draw arguments, their covering-white backdrop, generation,
output dimensions, and lossless encoding checks remain mandatory. Unknown sizes
still fall back. Locator rounding at fractional canvas coordinates can add one
pixel and remains a fail-closed fallback limitation; the 764px fix uses verified
native pixels without changing screenshot bounds or resizing images. On
2026-10-10, product/episode 6913:2770415 passed all 20 pages through explicit END
and the standard manual CLI packager, with 20 validated 764x1200 lossless WebP
ZIP members and no PNG fallback. Details, tests, and limits are in
[the current note](../../../../note/09_piccoma.md#764px-native-support-and-remaining-png-fallback-limit-2026-10-10).

Phases 03 and 04 passed independent review with BLOCKING 0. Phase 05 independently verified full and incremental Discovery, direct-only planning, and the real standard Batch-to-ZIP path for one current free episode from each product. Tester and artifact audit passed; the final independent evidence/design review passed with BLOCKING 0. Detailed results and limits are recorded below and in [runbook progress](../../../../runbooks/piccoma-free/PROGRESS.md).

The Phase 06-B/Tester PNG checkpoints are historical. Phase 06-D code review and independent live Tester verification passed with BLOCKING 0. The standard Batch-to-ZIP route produced 24 and 15 lossless WebP pages for the two selected products, with exact VP8L validation and no fallback. See the current live evidence and limits below and [runbook progress](../../../../runbooks/piccoma-free/PROGRESS.md).

## Runtime pacing

Phase 07 Stage A passed independent review. The distributed root `crawler.yaml` sets Piccoma `page_turn_delay_ms` to 200 and keeps `inter_candidate_delay_ms` at 3000 with the existing stop flags enabled. Both manual CLI and Batch use the existing site-neutral settings loader and resolve this value into `RunConfig`; no Piccoma-specific fallback or shared runtime change was added. If the Piccoma setting is absent, the common 1000ms fallback still applies. The delay remains once after save/progress and before the initial `go_next`, outside the page-change timeout. Rendering stability checks remain unchanged.

Phase 07 Stage B transports all six existing fresh native-trace snapshots as JSON strings and restores full dictionaries for the same Python validators and signatures. It preserves field values and intentional nulls, rejects unsupported JavaScript values/negative zero/ambiguous or oversized payloads, and treats transport/schema errors as unknown target state so Core fallback cannot proceed without continuity proof. Independent Stage B review passed. Call count/order, source-native JPEG binding, 408-draw replay, white composite, lossless WebP method6, encode-time and post-encode verification, and DPR raw-viewport equality are unchanged.

Stage C used the reviewed object and JSON implementations with the same YAML `page_turn_delay_ms: 200` setting in four interleaved 12-page manual runs. All 48 corresponding source-native lossless WebP files were byte-identical with zero fallback. Mean normal cycle time was 3.601s (object) versus 2.743s (JSON), a measured 0.857s / 23.8% reduction in these runs; trace RPC time fell by 0.864s and JSON decoding added 0.034s. WebP method6, pacing, and page-change stability time were effectively unchanged. A dedicated 24-page Batch reached explicit END and passed ZIP CRC, lossless-member, Artifact hash/size, and Catalog checks. The fresh prepackage audit also verified all 24 per-page manifest entries, 144 native evaluations, and 144 JSON decodes, while retaining no URLs/titles/raw manifest. The final Stage C review passed with BLOCKING 0. Details and measurement limits are in the [Phase 07 profile](../../../../research/piccoma-performance/PHASE07_PROFILE.md) and [Tester report](../../../../research/piccoma-performance/PHASE07_TESTER.md).



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
samples before its movement begins. During an already requested sequential
scaled-page transition only, `_wait_for_body` now excludes out-of-frame canvases
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
Canvas/frame left edges agree; canvas top is frame top + 0.5. The existing 1:1
geometry rule rejected this downscaled presentation. The strict new profile
requires these measured dimensions/offsets, existing in-frame/viewport/DPR and
ancestor visibility proof, and exact raw geometry equality throughout capture.
It returns the backing size for output; no crop, display screenshot, forced
canvas resize, or reflow is used by production capture.

Each page has exactly 1056 trace events: context creation, two backing resets,
and a complete 27x39 grid of 1053 image draws. The final destination row is 20px;
the exact source heights are 50.01 or 20.01. Source object/URL/load-generation,
unique first-party baseline JPEG response, exact context/draw arguments and
complete unique source/destination grids remain mandatory. Only the explicit
1350x1920 grid was added; nearby/unknown sizes are not inferred as supported.
Per-target trace capacity is now 1152 events; the bounded document total is
32768, sufficient for the observed 22x1056 events. Retained canvases (16), active
traces (128), 8 MiB full-JSON transport, 131072 traversal nodes, 8,000,000-byte
per-source budget and existing episode byte/replay-time limits remain unchanged.
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

The owned Page starts at 1904x1200 before navigation. The horizontal viewer accepts only that viewport and a finite numeric DPR within `1e-7` of 1.0. This narrow allowance covers the live Chrome reading `1.0000000298023224` (about `3e-8` above 1) while rejecting ordinary scaled modes such as 1.25x and 2x; the raw viewport array must still match exactly before and after each capture. The tolerance changes no canvas, frame, renderability, source, or draw geometry checks. Synthetic browser tests cover an unchanged near-1 DPR capture and fail-closed behavior when DPR changes within the supported band during capture. The bounded live verification and its limits are recorded below. Live raw canvas readback raised `SecurityError`. For the observed horizontal viewer, the adapter proves one loaded JPEG response's exact URL and image load generation against a complete single-image 408-draw canvas trace, replays the exact fractional draw arguments and context state into a detached canvas, and composites the transparent result over a proven solid-white backdrop. The white-paint proof requires computed `background-clip:border-box`, `clip:auto`, no border widths/radius, and the other validated covering-area conditions. Per-target dimension observers detect same-value attribute resets even while the canvas is detached and are bounded to source candidates/current capture targets. For the 1200px-high profiles, native output is lossless WebP encoded from verified source-derived RGB pixels; the payload must be a single VP8L chunk, decode at the expected dimensions, and reproduce every RGB byte. Raw tiled JPEG bytes are never page output. If WebP encoding or round-trip validation fails, the same verified native pixels remain PNG with an explicit encoding fallback reason. If source attribution is unavailable before materialization, Core `capture_locator` remains PNG and is accepted only while the active canvas generation stays unchanged for the entire capture. A canvas mutation during either path fails closed. Source response URLs and raw source JPEG bodies are not exposed in manifests/logs or committed; verified output page images are saved normally.

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
