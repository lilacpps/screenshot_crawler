# Piccoma current implementation snapshot

Updated: 2026-10-10. Phases 01-05 remain accepted. Phase 06-B's source-derived PNG replay and Phase 06-C's bounded p1-only JPEG coefficient feasibility work are historical accepted checkpoints. Phase 06-D defaults verified replay pixels to lossless WebP, retaining native PNG if encoding/round-trip proof fails and Core PNG if native provenance is unavailable. Phase 06-D code review and independent live Tester both passed with BLOCKING 0. Local Piccoma tests passed 99, packaging tests 26, and Ruff/diff checks passed; the full suite was not rerun after final site-local adjustments. The current two-product live route verified all 39 WebP pages through ZIP and Catalog completion. Phase 07 Stage A/B passed independent review. Stage C's interleaved manual comparison, 24-page Batch END/ZIP/Catalog run, and fresh per-page manifest audit passed; final Stage C Reviewer review passed with BLOCKING 0. Evidence and limits are in the [Phase 07 live profile](../research/piccoma-performance/PHASE07_PROFILE.md) and [Tester report](../research/piccoma-performance/PHASE07_TESTER.md).

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

Live canvas `getImageData` raised `SecurityError`, so direct canvas readback remains unavailable. The supported native horizontal rendering path is explicitly limited to backing widths 764, 842, or 844 and height 1200, and requires one loaded HTML image bound to one unique exact first-party JPEG response and stable load generation. Width 764 uses the observed 16-column / 24-row grid with 384 draws; widths 842/844 retain the 17-column / 24-row grid with 408 draws. Each accepted trace requires exactly three setup events plus that grid's draw count, complete unique source and destination grids, and the unchanged source/context/generation checks. Replay output must report the validated trace's exact draw count. Other stable canvas sizes can reach the Core PNG fallback but are not native-replay supported. The adapter records complete draw arguments and supported 2D context state without changing the page renderer. It replays the exact fractional source/destination rectangles and state into a detached canvas using the browser's normal image decoder, then composites the transparent replay over a separately validated solid-white paint ancestor. The current output encodes these verified RGB pixels as lossless WebP. Acceptance requires one simple VP8L chunk, the expected decoded dimensions, and exact equality of every RGB byte. It does not save tiled JPEG bytes as a page or change canvas security/backing settings. If WebP encoding or proof fails, the already verified native result remains PNG with a sanitized encoding-fallback reason. If native attribution/replay proof is unavailable before materialization, Core canvas/Locator capture remains PNG and requires an unchanged target generation.

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
