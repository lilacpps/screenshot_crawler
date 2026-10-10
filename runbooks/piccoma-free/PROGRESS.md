# Piccoma free-only implementation progress

Date: 2026-10-09
Branch: `feat/piccoma-adapter`
Last committed implementation checkpoint: `8fcfb00` (Phase 06-C)
Current status: Phases 01-05 and Phase 06-B/C are accepted checkpoints; Phase 06-B/C PNG/JPEG findings are historical. Phase 06-D implements lossless WebP from the verified source-derived RGB path, with validated native PNG on encoding failure and guarded Core PNG when provenance is unavailable. Phase 06-D code review and independent live Tester both passed with BLOCKING 0. The focused Piccoma and packaging selections, Ruff, and diff checks passed; the full suite was not rerun after the final site-local changes. A 2026-10-10 bounded two-run profile also verified 24/24 current native WebP page captures after the DPR tolerance adjustment; it stopped at `max_pages`, so END was not confirmed and it is not a full crawl. Phase 07 Stages A and B passed independent review. Stage C's interleaved manual comparison, dedicated 24-page Batch END/ZIP/Catalog checks, and fresh per-page Batch Manifest audit passed. The final Stage C Reviewer gate passed with BLOCKING 0. See the linked Phase 07 reports for exact metrics and scope.

| Phase | Status | Evidence |
| --- | --- | --- |
| 01 Site probe | Accepted | Complete listings and conservative access signals observed for products 28600 and 28606. Viewer evidence is summarized below. |
| 02 Discovery | PASS, BLOCKING 0 | Independent review passed with 60 tests passed and 0 skipped. Commit `053cf79`. |
| 03 Viewer/Capture | PASS, BLOCKING 0 | Independent review reported 174 passed and 0 skipped. Both free seeds traversed from p1 through explicit END; first/middle/last rendered captures were inspected. |
| 04 Site Policy/Batch | PASS, BLOCKING 0 | Independent review reported 130 passed and 0 skipped; local policy/Planner and standard Batch/Manifest/ZIP/Catalog tests pass. |
| 05 E2E | PASS, BLOCKING 0 | Independent Tester and final audit verified Discovery, Catalog, Batch, Crawl, Manifest and ZIP for one currently free episode from each product. |
| 06-B historical source-derived PNG | PASS, BLOCKING 0; independent Tester PASS | Exact single-JPEG/408-tile replay handled all 39 pages in the final two-product live E2E with no fallback under the prior PNG output contract; six selected same-page RGB comparisons and visual checks passed. Unsupported or mutated states fail closed or use the unchanged Core capture fallback only when target generation is stable. |
| 06-C JPEG coefficient feasibility | PASS, independent evidence/design review PASS, BLOCKING 0 | `jpeglib.read_dct` succeeded on both p1 JPEG bodies, but the unchanged Jump+ feasibility helper rejected each exact fractional tile map as `tile_geometry_not_mcu_aligned`; no implementation change. |
| 06-D lossless WebP output | PASS, code Reviewer PASS and independent live Tester PASS; BLOCKING 0 | All 39 selected pages used validated VP8L lossless WebP without fallback; six current Core RGB comparisons were exact. Standard ZIP/Manifest/Catalog/END checks passed. See the live evidence section below. |
| Bounded performance recheck (2026-10-10) | Capture verified; END unverified by design | Two 12-page runs used current DPR acceptance and captured ordered p1..p12 as native WebP with 0 fallback. They stopped at `max_pages`; see the bounded timing section below and [PROFILE](../../research/piccoma-performance/PROFILE.md#full-current-pipeline-live-profile-handoff-two-runs). |
| 07 JSON transfer / configured pacing (2026-10-10) | Stage A/B REVIEW PASS; Stage C evidence PASS / FINAL REVIEW PASS / BLOCKING 0 | [Phase 07 runbook](07-performance/README.md): Piccoma YAML200ms resolved through actual CLI and Batch paths; inter-candidate delay 3000ms, common fallback and other sites unchanged. All six native snapshots use full JSON transport and restore for existing validation. Four interleaved 12-page manual runs yielded 48/48 byte-identical native lossless-WebP files and 0 fallback; normal cycle mean was 3.601s object vs 2.743s JSON (-0.857s/23.8%). Dedicated 24-page Batch reached explicit END and passed ZIP/Catalog checks; fresh prepackage Manifest audit passed for all 24 pages (144 native evaluations/144 JSON decodes). Final Reviewer gate passed with BLOCKING 0. Method6 and rendering stability remain unchanged. See [profile](../../research/piccoma-performance/PHASE07_PROFILE.md), [Tester report](../../research/piccoma-performance/PHASE07_TESTER.md), and [numeric measurements](../../research/piccoma-performance/PHASE07_MEASUREMENTS.json). |

## Phase 01 listing and access evidence

The Phase 01 probes used the existing shared Crawler Chrome through BrowserSession/CDP and closed only their own pages. Phase 01 diagnostic evidence is sanitized metadata only and contains no page image payloads, cookies, storage state, or signed URLs. Separate Phase 03 rendered QA PNGs and Phase 04 synthetic Batch artifacts are local ignored test outputs; they are not committed.

On 2026-10-09, the product listing pages returned HTTP 200. Each exposed one `#js_episodeList.PCM-list_asc`; the live row count matched the declared count, IDs were unique, product IDs matched, titles were present, and the requested seed episode was present. Native DOM order is oldest-to-newest. Discovery reverses rows to canonical latest-to-oldest while assigning global display position as original DOM index + 1 before applying inclusive bounds.

| Product | Declared and observed rows | Observed access states | Seed positions in oldest-first DOM |
| --- | ---: | --- | --- |
| 28600 | 432 / 432 | 432 exact-free rows | 1910027 at index 0; 4142286 at index 421 |
| 28606 | 218 / 218 | 12 exact-free; 167 wait/binge-free; 39 point-priced | 2001009 at index 1 |

Free requires the exact status marker set `{PCM-epList_status_free}` from the status wrapper and descendants plus the exact visible price `¥0`. Conflicting markers or other ambiguous states are unknown. A positive point price is paid; wait-free is quota. Generic status labels, personal readability, and `data-user_access=require` do not prove unconditional free access. Listing counts are snapshots, not constants.

## Phase 02 Discovery checkpoint

Piccoma-local Discovery parses strict viewer/listing URLs, buffers and validates the entire native list before yielding, and preserves product-scoped `product_id:episode_id` identities and whole-work display positions. The existing Discovery service owns Catalog persistence and full/incremental behavior. The Phase 02 independent review's two blocking findings (strict final listing URL validation and wrapper-level status markers) were fixed; rediscovery also verifies free-to-paid/quota/unknown access refresh while retaining completed Item status. The independent gate reported 60 passed and 0 skipped.

## Phase 03 observed viewer and capture contract

Before each viewer entry, the adapter opens that product's current episode listing and requires the target row to remain exact-free. It then verifies the requested composite product/episode URL and HTTP 200 response. Only `auto` and `direct` are supported; both use this same fresh-free path. Quota, paid, unknown, and unsupported states stop without a fallback.

The observed reader root is `#react_ViewerApp`. The supported layout is horizontal and has body classes `PCM-stt_horizontal` and `PCM-prop_scroll_l`, with one `#react_PageListApp`, one `#js_frame.PCM-viewer2_frame`, and contiguous `p1..pN` body IDs followed by one `last` wrapper. The observed page sequence was p1 through pN using the in-episode next control; native DOM page-wrapper order is reversed. A body page is ready only when it is uniquely active, has one loaded canvas wrapper/canvas, all canvas ancestors are displayed and visible with opacity 1, and its geometry remains stable across three samples. After normalization to p1, unrequested cursor jumps and rewinds fail closed. Navigation uses the distinct in-episode `button.PCM-viewer2_pagingBtn_next` and `button.PCM-viewer2_pagingBtn_prev`; transitions wait for the expected active page ID. END is accepted only after advancing from the final body page to the active `#last` page with `#js_viewerEnd`.

A late resume prompt was observed. The adapter allows a bounded 1.5-second attachment grace and cancels only the unique, exact observed resume dialog with its two expected enabled buttons and no link. In addition to the numeric-page prompt, a last-page prompt was observed with exact normalized text `前回最後のページを 読んでいました。 最後のページに移動しますか？`; mixed numeric/last wording or extra text remains rejected. Other or ambiguous dialogs fail closed. The single #js_scrollTypeSing reading-direction sign is hidden only during capture after its root classes match one of two observed sets (base sign class alone, or base plus `_sh` and `_show`), while the two child groups, three expected image labels/classes, no meaningful text/interactive nodes, and empty pseudo-element content remain strictly checked; its prior inline style and visibility are restored. Unknown or duplicate guide markup fails closed.

The owned Page is prepared at a 1904x1200 viewport before navigation. Phase 03 used Core `capture_locator` and rendered screenshot PNG because raw canvas readback raised `SecurityError`. Phase 06-B subsequently proved a narrow source-derived path: one stable loaded HTML image and unique exact JPEG response account for all 408 tile draws into the selected body canvas. A detached canvas replays exact fractional source/destination rectangles and recorded context state through the browser's normal decoder; Pillow then composites the transparent replay PNG onto the separately proven solid-white backdrop. Phase 06-D encodes these verified RGB pixels as single-chunk lossless WebP only after a full exact round-trip check. Encoding failure keeps the verified replay as PNG with a reason; missing native proof uses guarded Core PNG capture. The raw tiled JPEG is never saved as a page.

Native replay output requires stable source-load generation, complete bounded canvas traces, unchanged active-target generation through final materialization, supported drawing state/operations, exact response identity, and the known white backdrop paint chain. Per-canvas dimension observers are retained only for source candidates/current capture targets, disconnected on retirement, and catch same-value NamedNodeMap mutations while a target is detached. White composition requires `background-clip:border-box`, `clip:auto`, zero border widths/radius, and the other validated covering-white paint conditions. Other image, attribution, trace, backdrop, and replay conditions fall back to Core `capture_locator` only while the active target generation remains unchanged; target mutation during either path fails closed. Successful native output metadata marks `native_tile_replay_lossless_webp`, `source_native=true`, `source_mime=image/jpeg`, `output_format=image/webp`, `output_lossless=true`, and the verified solid-white backdrop. If WebP encoding or exact round-trip validation fails after native provenance is established, verified native pixels are emitted as PNG with `native_tile_replay_png` and `encoding_fallback_reason`. If native source proof is unavailable, guarded Core capture remains PNG with `source_native=false` and `fallback_reason`. Output metadata describes the actual per-page result. Source response URLs and raw source JPEG bodies are not written to manifests/logs or committed; verified output page images are saved normally.

## Phase 03 live QA

On 2026-10-09, after Reviewer BLOCKING2 fixes, both targets were rechecked in their product listing immediately before entry. Each had exactly one target row with `PCM-epList_status_free` and `¥0`.

| Viewer | Body pages | Captures | Final state | Viewer path |
| --- | ---: | --- | --- | --- |
| 28600/1910027 | 24 | p1, p12, p24; each 844x1200 PNG | active `last`, explicit END | unchanged at `/web/viewer/28600/1910027` |
| 28606/2001009 | 15 | p1, p8, p15; each 842x1200 PNG | active `last`, explicit END | unchanged at `/web/viewer/28606/2001009` |

All six latest ignored PNGs were visually inspected: each showed a sharp, full-frame body without the reading-direction overlay or other reader chrome. The guide existed and was visible before and after every capture. The initial and terminal IDs/counts and screenshot dimensions are recorded in ignored `output/piccoma_experiment/phase03_b_live_capture_evidence.json`. No next-episode CTA or paid/quota action was used. The Lead separately inspected the 28600 p1 image.

## Phase 03 implementation verification

The latest focused command was:

```text
.venv/Scripts/python.exe -m pytest -q tests/integration/test_piccoma_adapter_browser.py tests/integration/test_piccoma_discovery_browser.py tests/unit/test_piccoma_discovery.py tests/unit/test_cli.py
174 passed, 288 warnings, 0 skipped
```

`ruff check src tests` and `git diff --check` passed after the documentation sync. The 288 warnings are pytest-asyncio event-loop-policy deprecations.

The adapter and browser-fixture tests cover strict identity and fresh-free preflight, redirected/wrong target failures, exact numeric and last-page resume prompts, delayed prompt, unknown-dialog rejection, current-page readiness/renderability and geometry, approved cursor transitions, rejection of unrequested jumps/rewinds, explicit END, the two observed guide class sets with exclusion/restoration, and PNG dimensions. Visibility regressions cover display, visibility, or zero opacity on the canvas and ancestors before capture, and visibility changes during capture. Guide tests reject unknown interactive nodes, appended text, and unexpected visible child elements. No real-image fixtures are stored in tests.

## Final result and limits

Phases 01-05 and Phase 06-B/C are accepted checkpoints. Phase 06-D code review and independent live Tester passed with BLOCKING 0. The standard two-product run completed all 39 pages as lossless WebP with explicit END and verified ZIP/Manifest/Catalog artifacts; this is the current-format E2E, while Phase 06-B PNG evidence remains historical. A later shared-CDP diagnostic exposed a floating-point DPR slightly above 1; the adapter now has a 1e-7 tolerance and exact raw viewport stability check. The updated gate passed two bounded 12-page live runs (24/24 native WebP, zero fallback); END was not checked by these bounded runs. Focused Piccoma/package selections and Ruff/diff checks pass; full pytest was not rerun after final site-local changes. Other draw/backdrop/resource variants and paid/quota flows remain unsupported/excluded. Preserve the pre-existing user edit to `watchlist.yaml` and untracked `debug.log`.

## Phase 04 Site Policy and local Batch checkpoint

`PiccomaSitePolicy` is registered for Batch. Only `available=true` plus `access_mode=free` produces an eligible `direct` decision. Quota, paid, owned, grant, rental, unknown, unavailable, and unrecognized states reject. Grant timestamps are ignored: available+free remains eligible, and active or expired grants never make non-free modes eligible. Piccoma declares no supported resource, resource pass, or grant-only flow. The generic Planner preserves Catalog ordering, composite identity, display-position prefix, and metadata. No Core or Catalog schema changes were made.

The synthetic local browser integration runs the standard Planner, BatchExecutor, Runner, Piccoma adapter, manifest, packager, and Catalog success update for a three-page source. It verifies ordered p1..p3 manifest entries and PNG members in the ZIP, a completed Item, successful CrawlRun and Artifact, and no quota/resource mutation. Stale-free listing, wrong composite candidate ID, and redirected viewer cases produce no ZIP, completed Item, or Artifact and do not mutate resource state.

Verification: policy/CLI unit tests 96 passed; Piccoma local browser integration 34 passed; combined affected Batch/Catalog/packaging/CLI/Piccoma suite 310 passed, 743 pytest-asyncio deprecation warnings, 0 skipped. `ruff check src tests` passed. Independent Phase 04 review: PASS, BLOCKING 0; 130 passed, 0 skipped.

## Phase 05 live E2E and final audit

On the 2026-10-09 isolated run, full CLI Discovery exhausted both product listings: 28600 returned 432/432 and 28606 returned 218/218, with contiguous whole-work positions. Incremental Discovery observed five known rows per product, added zero, and stopped at the existing `known_streak` rule. The read-only Batch plan selected 444 available/free candidates as direct and skipped 206 non-free candidates (`unsupported_access_mode`); quota was zero and there were no quota-resource rows. These are run observations, not constants.

| Product/episode | Body pages | PNG dimensions | Final result |
| --- | ---: | --- | --- |
| 28600/1910027 | 24 | 844x1200 | active END, unchanged target URL, succeeded Run, completed Item, ZIP Artifact present |
| 28606/2001009 | 15 | 842x1200 | active END, unchanged target URL, succeeded Run, completed Item, ZIP Artifact present |

The independent Tester used the normal BatchExecutor, Runner, production packager and Catalog finalization path. Each Manifest contained contiguous unique page IDs and the ZIP had exactly the Manifest members; ZIP CRC, capture-to-member hashes, Artifact checksum/size, page dimensions and status metadata passed. First/middle/last PNGs for both episodes were visually checked. Per-episode image audits found 24/24 unique SHA256s and 15/15 unique SHA256s, with zero duplicate groups. The wrapper only copied diagnostic Manifest/progress and image-hash metadata before delegating to the standard packager. No rights-consuming action was used; AccessGuard remained enabled for 403/429/challenge/CAPTCHA and configured max_pages/same-content bounds were retained.

Evidence reports are local ignored files at `output/piccoma_experiment/phase05_tester/evidence/phase05_tester_report.json`, `phase05_final_independent_audit.json`, and per-episode `image_audit_before_package.json`. No image payload, credentials or signed URL was committed. Live listing checks confirmed current free access before entry and `last_seen_at` was populated, but `access_checked_at` remained NULL; the live verification is evidenced by the run, not by that Catalog timestamp.

On Windows PowerShell, redirected/piped Batch Planner output initially failed under cp932 for a title containing U+8E20. The read-only command passed with task-local `PYTHONIOENCODING=utf-8` and `PYTHONUTF8=1`; no shared CLI change or lossy title conversion was made.

Final verification on implementation checkpoint `1e29fc8`: full `pytest -q` reported 1827 passed, 0 skipped in 330.93 seconds; `ruff check src tests` and `git diff --check` passed. Warnings were existing pytest-asyncio event-loop-policy deprecations and the intentional duplicate-ZIP-member fixture warning. Phase 05 Tester and independent final audit passed.

## Phase 06-B historical PNG capture checkpoint

The Phase 06 research gate established an exact source image → visible canvas graph for the observed horizontal rendering path. Production support is deliberately narrower than the research harness: one HTML image with a stable load generation, one uniquely matching exact JPEG response, and a complete 408-call canvas trace. The replay preserves original fractional source/destination rectangles (including observed `50.01` source-height values), context attributes and state, browser decoding, tile order, and canvas dimensions. No raw tiled JPEG is written as a page. Transparent replay is composited only after materialization, using the validated white backdrop gate.

The active target's generation is snapshotted independently of source-proof eligibility and checked through both native output and every screenshot fallback. Same-value dimension resets, namespace/Attr mutation paths, paint/draw changes, and active-target mutation during materialization fail closed. Source reassignment/reload without target mutation invalidates only the native optimization and may use the guarded existing Core screenshot fallback. Trace eviction clears retained event/source references while preserving lightweight generation monitoring; global overflow retires heavy traces and stops adding heavy data. Response, source-byte, event, and runtime limits remain enforced.

On 2026-10-09, production-method live validation rechecked exact-free listing entries and composite targets before using the existing shared CDP Page. For 28600/1910027 (24 body pages), p1/p12/p24 produced 844x1200 PNGs; for 28606/2001009 (15 body pages), p1/p8/p15 produced 842x1200 PNGs. Each reported `native_tile_replay_png`, `source_native=true`, `source_mime=image/jpeg`, and `source_backdrop=verified_solid_white`. RGB pixels matched the unchanged, clean Locator screenshot exactly on all six selected pages. Both runs reached explicit active END on the unchanged requested viewer URL. The guide stayed excluded/restored, and no paid/quota/entitlement action occurred. These six checks validate the observed replay path only; detached-canvas attribute-reset and `background-clip:text` rejection are synthetic browser regressions, not additional observed site variants. The sanitized summary is ignored at `output/piccoma_experiment/source_capture_research/phase06b_production_selected_live_evidence.json`; no response URL, image bytes, or image payload was committed.

## Phase 06 historical independent Tester E2E under PNG output contract (2026-10-09)

The independent Tester report is at ignored `output/piccoma_experiment/phase06_tester/runs/20261009T053043Z-08fcc951/evidence/phase06_tester_report.json`. Full Discovery exhausted 432/432 rows for product 28600 and 218/218 for product 28606. Incremental Discovery observed five known rows per product, added none, and stopped at `known_streak`. The read-only Batch plan had 444 eligible/direct candidates, 206 skipped non-free candidates, and zero quota candidates. Runtime protections remained active for 403, 429, challenge, and CAPTCHA responses, with `max_pages=1000` and `max_same_content=3`. These are run counts, not constants.

| Product/episode | Pages | Output | Final state |
| --- | ---: | --- | --- |
| 28600/1910027 | 24 | 844x1200 PNG | `native_tile_replay_png` on all pages; explicit END; succeeded Run; completed Item; ZIP Artifact present |
| 28606/2001009 | 15 | 842x1200 PNG | `native_tile_replay_png` on all pages; explicit END; succeeded Run; completed Item; ZIP Artifact present |

The normal BatchExecutor -> Runner -> packager -> Catalog path produced all 39 pages with `source_native=true`, JPEG source MIME, and `verified_solid_white`; no page used fallback. Page IDs were ordered and unique, every page hash in each episode was distinct, ZIP members exactly matched the Manifest, and CRC/member hashes plus Catalog Artifact checks passed. Six current first/middle/last same-page RGB comparisons and six visual checks passed. Sources remained available/free, quota/grant fields were unchanged, and quota resource rows remained 0 before and after. Both viewers stayed on the requested URL through END. No paid or entitlement action occurred.

The final Reviewer independently audited actual ZIPs against the Manifest and read-only Catalog data and verified the six current image comparisons: PASS, BLOCKING 0.

Current verification and review status: the blocker-focused selection passed 16 tests with 72 deselected and five existing pytest-asyncio warnings. It covers detached same-value NamedNodeMap reset, background-clip:text rejection on partial-alpha pixels, white-backdrop invariants, and related paint-gate regressions. The affected suite also covers the target-reset fallback race, RGB-difference detection, partial-alpha compositing, bounded trace eviction/overflow, source reload, and visible overlapping sibling fallback. The broader scoped suite passed 249 tests, 306 pytest-asyncio deprecation warnings, and 0 skipped. `ruff check src tests` and `git diff --check` passed; new-file whitespace/EOF checks passed. Final independent Reviewer gate: PASS, BLOCKING 0. The full `pytest -q` run passed on the checkpoint immediately before the final compatibility fix (1881 passed, 3558 warnings, 0 skipped, 353.38 seconds); the final fix was tested separately and is covered by the final Reviewer pass. Unsupported layouts, unobserved source/draw graphs, changed/unknown backdrops, missing/ambiguous responses, overflow, and target mutation remain unsupported or fail closed.

The final compatibility regression passed 1 browser test (48 deselected, 0 skipped, five existing pytest-asyncio warnings): the hooked two-argument namespace-removal call on a non-canvas `div` matched the native method's returned attribute and removal result. Final Reviewer gate: PASS, BLOCKING 0.

Exact test selections:

```text
.venv/Scripts/pytest.exe -q tests/unit/test_piccoma_native_capture.py tests/integration/test_piccoma_adapter_browser.py -k "detached_named_map or background_clip_text or white_backdrop_gate"
16 passed, 72 deselected, 5 warnings

.venv/Scripts/pytest.exe -q tests/unit/test_piccoma_native_capture.py tests/unit/test_piccoma_discovery.py tests/unit/test_piccoma_policy.py tests/integration/test_piccoma_discovery_browser.py tests/integration/test_piccoma_adapter_browser.py tests/unit/test_comicdays_native_capture.py tests/unit/test_bookwalker_native_capture.py
249 passed, 306 warnings, 0 skipped
```

## Phase 06-C actual JPEG coefficient feasibility (2026-10-09)

The bounded p1-only probe refreshed exact-free listing status and composite target identity before entering 28600/1910027 and 28606/2001009. Both production traces were complete at 408 draws with one unique exact observed `image/jpeg` response, of 1,951,370 and 789,375 bytes respectively. The response bodies passed the existing 8 MB limit. `jpeglib.read_dct` parsed both baseline 8-bit, three-component 4:4:4 JPEGs with 8x8 MCUs; temporary files were removed. The probe used zero forward transitions and zero rights/entitlement actions, then closed both owned Pages and disconnected its CDP session. Sanitized evidence only is at ignored `output/piccoma_experiment/source_capture_research/phase06c_jpeglib_p1_evidence.json`; no source URL, bytes, or image payload was saved.

The actual 408 draw mappings contain 50-pixel body tiles with 44-pixel (28600) and 42-pixel (28606) edge widths. Source crop heights are exactly `50.01`, destination heights are `50`, and recorded image smoothing is enabled with quality `low`. The exact observed fractional rectangles were passed unchanged to the unmodified Jump+ `dct_lossless_feasibility`; both returned `tile_geometry_not_mcu_aligned`. Existing Jump+/Magapoke coefficient permutation requires integer, equal-size, MCU-aligned rectangles, so that existing method cannot operate on this graph. This is limited to the existing coefficient method, not a claim that every custom JPEG transform is impossible. The first destination 8x8 block begins at source phase (6,6) for 28600 and (6,2) for 28606 and spans multiple source DCT blocks. None of 24 central 4x4 tile groups was a contiguous translated source group in either trace. The equal-50-height seam/phase and group calculation is diagnostic only; no production geometry is rounded or normalized. At the Phase 06-C checkpoint, output was the verified reconstructed/composited PNG; Phase 06-D subsequently adds lossless WebP encoding without changing replay geometry. The independent evidence/design review passed with BLOCKING 0. The isolated probe passed `py_compile` and Ruff; this docs/research-only checkpoint did not rerun unit, integration, or full-suite tests.

## Phase 06-D lossless WebP implementation (2026-10-09)

Phase 06-D preserves all existing Piccoma native replay, exact-source binding,
white-backdrop, reader cursor, target visibility/generation, access, and END
guards. After the verified transparent replay has been composited into RGB
pixels, the default native output uses the Pillow WebP encoder with
lossless=True, method=6. Output acceptance requires one exact VP8L chunk,
consistent RIFF/chunk lengths, expected dimensions encoded in the VP8L header,
successful full decode, a single frame, MIME/extension agreement, and exact
equality of every decoded RGB byte against the verified composite. Lossy WebP
is rejected even for a degenerate image whose decoded RGB happens to match.

If WebP encoding or round-trip validation fails, capture keeps the same
verified native replay pixels as PNG and reports encoding_fallback_reason.
If source provenance is unavailable before materialization, the guarded Core
canvas/Locator path stays PNG and rejects WebP returned under PNG method
metadata. The active canvas generation is checked after encoding; a reset
during materialization fails closed. Per-page metadata distinguishes
native_tile_replay_lossless_webp, native_tile_replay_png, and
core_canvas_or_locator_png, and reports the actual output format/lossless
state. Source response URLs and raw source JPEG bodies are not written to manifests/logs or committed; verified output page images are saved normally.

Focused verification passed 99 Piccoma unit/browser tests and 26 packaging tests,
with zero skips; `ruff check src tests` and `git diff --check` passed. The code
Reviewer passed with BLOCKING 0. The independent live Tester report is ignored
at `output/piccoma_experiment/phase06d_tester/runs/20261009T073152Z-3e91e9e0/evidence/phase06_tester_report.json`.

The Tester exhausted full Discovery at 432/432 rows for 28600 and 218/218 for
28606. Incremental Discovery observed five known rows on each product, added
none, and stopped at `known_streak`. The read-only Batch plan had 444 direct
eligible candidates, 206 skipped non-free candidates, and zero quota
candidates; these counts describe this run, not constants.

| Target | Pages and dimensions | Capture / terminal result |
| --- | ---: | --- |
| 28600/1910027 | 24 at 844x1200 | All 24 used `native_tile_replay_lossless_webp`; explicit END on the unchanged requested URL |
| 28606/2001009 | 15 at 842x1200 | All 15 used `native_tile_replay_lossless_webp`; explicit END on the unchanged requested URL |

All 39 Manifest pages had ordered unique page IDs and unique SHA256 payloads
within their episode. Each used `source_native=true`, JPEG source MIME,
`verified_solid_white`, `image/webp`, and `output_lossless=true`; none used an
encoding or provenance fallback. The independent simple RIFF/VP8L parser
verified lossless chunk structure, dimensions, and lengths. ZIP members exactly
matched the Manifest and passed CRC/member hash checks; Artifact hash/size,
completed Items, succeeded END Runs, and present Artifacts passed. Current
same-page comparisons with the unchanged Core capture passed with zero RGB
changed pixels at 28600 p1/p13/p24 and 28606 p1/p8/p15; all six were visually
reviewed. The earlier 39-page PNG comparison also matched RGB exactly, but is
secondary historical evidence.

Observed verified JPEG response bodies totaled 37,346,355 bytes; lossless
WebP outputs totaled 25,356,052 bytes (-32.11%) in this run. By product,
28600 measured 26,159,334 source JPEG bytes to 18,055,076 WebP bytes (-30.98%),
and 28606 measured 11,187,021 to 7,300,976 bytes (-34.74%). No page's WebP
exceeded its corresponding observed JPEG body size. This is a measurement of
these 39 pages, not a general size guarantee. Both targets remained
available/free; quota and grant fields were unchanged, and Piccoma resource
rows remained zero before and after. No entitlement action was performed.
Historical live captures verified the horizontal layout at 1904x1200 and exact
DPR 1. A later shared-CDP diagnostic observed `devicePixelRatio` as
`1.0000000298023224` at the same viewport. The adapter previously required an
exact DPR value of 1 and stopped before the normal capture loop. The current
code accepts finite numeric DPR values with `abs(DPR - 1) <= 1e-7`, while
rejecting bool/non-finite values and normal scaled modes. It retains all
existing viewport dimensions, canvas/backing/frame/renderability checks, and
requires the full raw viewport array to be unchanged across capture. Pure
validation cases, local Chromium capture tests, and the bounded live runs below
cover acceptance; local regression also rejects an in-band DPR change during
capture. This tolerance is not evidence for another reader layout. Other
reader/draw/backdrop/resource variants remain unsupported. Downstream WebP
reader compatibility outside the tested browser/Pillow/ZIP path was not
separately verified.

## 2026-10-10 bounded performance recheck

Using the existing shared Crawler Chrome over CDP 9222, the Tester created a
fresh uncredentialed owned context, freshly confirmed the exact-free listing
for 28600/1910027, and ran two bounded passes. Each pass captured pages p1..p12
in order as `native_tile_replay_lossless_webp`: **24/24 native WebP captures,
zero fallbacks, no gap or duplicate**. The near-1 DPR was accepted. The normal
1,000 ms pacing, method-6 lossless WebP encoder, full object trace returns, and
source/provenance/generation/output guards were retained, so this is a baseline
profile rather than an optimization A/B.

The driver stopped at its configured `max_pages` bound after p12. It did not
capture p13 or observe active END. This is bounded live capture evidence, not
a full-episode completion or END verification. Historical Phase 06-D live
E2E remains the separate evidence for full episodes reaching END, ZIP/Manifest
consistency, and Catalog completion. Both current profile runs used isolated
outputs; they did not modify normal outputs or Catalog and performed no paid,
ticket, or quota action.

Across 20 complete steady-page intervals measured from capture start of pN to
capture start of pN+1, wall time was mean **4.538 s**, median **4.151 s**, p90
**5.627 s**, maximum **5.772 s**. The two p1 intervals were **5.571 s** and
**5.398 s**. For those same 20 cycles, stage medians include fixed pacing
**1.008 s**, page turn through stable completion **0.724 s**, and
`capture_page()` **2.234 s**. These top-level stages are disjoint, but their
medians must not be added to obtain the cycle median. Detailed stage distributions,
transition anchors, measurement limits, and unmeasured causes are in the
[current performance profile](../../research/piccoma-performance/PROFILE.md#full-current-pipeline-live-profile-handoff-two-runs).

The full suite result remains 1881 passed, 3558 warnings, and 0 skipped on the reviewed checkpoint immediately before the final NamedNodeMap compatibility fix. That fix was tested separately; the suite was not rerun after it or the final Phase 06-D site-local changes.
