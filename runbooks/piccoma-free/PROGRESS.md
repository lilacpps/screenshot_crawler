# Piccoma free-only implementation progress

Date: 2026-10-09
Branch: `feat/piccoma-adapter`
Last committed implementation checkpoint: `8be62be` (Phase 06-B)
Current status: Phases 01-05 accepted. Phase 06-B passed final independent Reviewer review (PASS, BLOCKING 0) and independent Tester E2E (PASS). All 39 pages in the two-product live Batch-to-ZIP run used the strict source-derived PNG replay contract below. Phase 06-C's bounded p1-only JPEG coefficient-feasibility probe and independent evidence/design review passed with BLOCKING 0. The full suite passed on the checkpoint immediately before the final NamedNodeMap argument-forwarding compatibility fix; that fix passed its separate focused browser test and final Reviewer gate.

| Phase | Status | Evidence |
| --- | --- | --- |
| 01 Site probe | Accepted | Complete listings and conservative access signals observed for products 28600 and 28606. Viewer evidence is summarized below. |
| 02 Discovery | PASS, BLOCKING 0 | Independent review passed with 60 tests passed and 0 skipped. Commit `053cf79`. |
| 03 Viewer/Capture | PASS, BLOCKING 0 | Independent review reported 174 passed and 0 skipped. Both free seeds traversed from p1 through explicit END; first/middle/last rendered captures were inspected. |
| 04 Site Policy/Batch | PASS, BLOCKING 0 | Independent review reported 130 passed and 0 skipped; local policy/Planner and standard Batch/Manifest/ZIP/Catalog tests pass. |
| 05 E2E | PASS, BLOCKING 0 | Independent Tester and final audit verified Discovery, Catalog, Batch, Crawl, Manifest and ZIP for one currently free episode from each product. |
| 06-B source-derived PNG | PASS, BLOCKING 0; independent Tester PASS | Exact single-JPEG/408-tile replay handled all 39 pages in the final two-product live E2E with no fallback; six selected same-page RGB comparisons and visual checks passed. Unsupported or mutated states fail closed or use the unchanged Core capture fallback only when target generation is stable. |
| 06-C JPEG coefficient feasibility | PASS, independent evidence/design review PASS, BLOCKING 0 | `jpeglib.read_dct` succeeded on both p1 JPEG bodies, but the unchanged Jump+ feasibility helper rejected each exact fractional tile map as `tile_geometry_not_mcu_aligned`; no implementation change. |

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

The owned Page is prepared at a 1904x1200 viewport before navigation. Phase 03 used Core `capture_locator` and rendered screenshot PNG because raw canvas readback raised `SecurityError`. Phase 06-B subsequently proved a narrow source-derived path: one stable loaded HTML image and unique exact JPEG response account for all 408 tile draws into the selected body canvas. A detached canvas replays exact fractional source/destination rectangles and recorded context state through the browser's normal decoder; Pillow then composites the transparent replay PNG onto the separately proven solid-white backdrop. The raw tiled JPEG is never saved as a page.

Native replay output requires stable source-load generation, complete bounded canvas traces, unchanged active-target generation through final materialization, supported drawing state/operations, exact response identity, and the known white backdrop paint chain. Per-canvas dimension observers are retained only for source candidates/current capture targets, disconnected on retirement, and catch same-value NamedNodeMap mutations while a target is detached. White composition requires `background-clip:border-box`, `clip:auto`, zero border widths/radius, and the other validated covering-white paint conditions. Other image, attribution, trace, backdrop, and replay conditions fall back to Core `capture_locator` only while the active target generation remains unchanged; target mutation during either path fails closed. Successful output metadata marks `native_tile_replay_png`, `source_native=true`, `source_mime=image/jpeg`, and `source_backdrop=verified_solid_white`; safe fallback identifies `source_native=false` and a sanitized reason. No signed URL, response body, or image payload is stored in repository evidence.

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

Phases 01-05 are accepted; Phase 04 review and Phase 05 Tester/final artifact audit passed with BLOCKING 0. Phase 06-B final Reviewer and independent Tester gates also passed with BLOCKING 0. The two-product live route completed all 39 pages using source-derived PNG replay and reached explicit END. Remaining limits are the observed horizontal layout at 1904x1200/DPR 1, unsupported draw/backdrop/resource variants, and paid/quota flows. Preserve the pre-existing user edit to `watchlist.yaml` and untracked `debug.log`.

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

## Phase 06-B source-derived capture implementation checkpoint

The Phase 06 research gate established an exact source image → visible canvas graph for the observed horizontal rendering path. Production support is deliberately narrower than the research harness: one HTML image with a stable load generation, one uniquely matching exact JPEG response, and a complete 408-call canvas trace. The replay preserves original fractional source/destination rectangles (including observed `50.01` source-height values), context attributes and state, browser decoding, tile order, and canvas dimensions. No raw tiled JPEG is written as a page. Transparent replay is composited only after materialization, using the validated white backdrop gate.

The active target's generation is snapshotted independently of source-proof eligibility and checked through both native output and every screenshot fallback. Same-value dimension resets, namespace/Attr mutation paths, paint/draw changes, and active-target mutation during materialization fail closed. Source reassignment/reload without target mutation invalidates only the native optimization and may use the guarded existing Core screenshot fallback. Trace eviction clears retained event/source references while preserving lightweight generation monitoring; global overflow retires heavy traces and stops adding heavy data. Response, source-byte, event, and runtime limits remain enforced.

On 2026-10-09, production-method live validation rechecked exact-free listing entries and composite targets before using the existing shared CDP Page. For 28600/1910027 (24 body pages), p1/p12/p24 produced 844x1200 PNGs; for 28606/2001009 (15 body pages), p1/p8/p15 produced 842x1200 PNGs. Each reported `native_tile_replay_png`, `source_native=true`, `source_mime=image/jpeg`, and `source_backdrop=verified_solid_white`. RGB pixels matched the unchanged, clean Locator screenshot exactly on all six selected pages. Both runs reached explicit active END on the unchanged requested viewer URL. The guide stayed excluded/restored, and no paid/quota/entitlement action occurred. These six checks validate the observed replay path only; detached-canvas attribute-reset and `background-clip:text` rejection are synthetic browser regressions, not additional observed site variants. The sanitized summary is ignored at `output/piccoma_experiment/source_capture_research/phase06b_production_selected_live_evidence.json`; no response URL, image bytes, or image payload was committed.

## Phase 06 final independent Tester E2E (2026-10-09)

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

The actual 408 draw mappings contain 50-pixel body tiles with 44-pixel (28600) and 42-pixel (28606) edge widths. Source crop heights are exactly `50.01`, destination heights are `50`, and recorded image smoothing is enabled with quality `low`. The exact observed fractional rectangles were passed unchanged to the unmodified Jump+ `dct_lossless_feasibility`; both returned `tile_geometry_not_mcu_aligned`. Existing Jump+/Magapoke coefficient permutation requires integer, equal-size, MCU-aligned rectangles, so that existing method cannot operate on this graph. This is limited to the existing coefficient method, not a claim that every custom JPEG transform is impossible. The first destination 8x8 block begins at source phase (6,6) for 28600 and (6,2) for 28606 and spans multiple source DCT blocks. None of 24 central 4x4 tile groups was a contiguous translated source group in either trace. The equal-50-height seam/phase and group calculation is diagnostic only; no production geometry is rounded or normalized. The accepted production output remains the verified reconstructed/composited PNG. The independent evidence/design review passed with BLOCKING 0. The isolated probe passed `py_compile` and Ruff; this docs/research-only checkpoint did not rerun unit, integration, or full-suite tests.
