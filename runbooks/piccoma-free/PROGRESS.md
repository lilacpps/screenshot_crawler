# Piccoma free-only implementation progress

Date: 2026-10-09
Branch: `feat/piccoma-adapter`
Last committed implementation checkpoint: `1e29fc8` (Phase 04)
Current status: Phases 01-05 accepted. Phase 02, 03, 04 independent reviews and Phase 05 Tester/final audit all PASS with BLOCKING 0. Full suite and Ruff pass.

| Phase | Status | Evidence |
| --- | --- | --- |
| 01 Site probe | Accepted | Complete listings and conservative access signals observed for products 28600 and 28606. Viewer evidence is summarized below. |
| 02 Discovery | PASS, BLOCKING 0 | Independent review passed with 60 tests passed and 0 skipped. Commit `053cf79`. |
| 03 Viewer/Capture | PASS, BLOCKING 0 | Independent review reported 174 passed and 0 skipped. Both free seeds traversed from p1 through explicit END; first/middle/last rendered captures were inspected. |
| 04 Site Policy/Batch | PASS, BLOCKING 0 | Independent review reported 130 passed and 0 skipped; local policy/Planner and standard Batch/Manifest/ZIP/Catalog tests pass. |
| 05 E2E | PASS, BLOCKING 0 | Independent Tester and final audit verified Discovery, Catalog, Batch, Crawl, Manifest and ZIP for one currently free episode from each product. |

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

The owned Page is prepared at a 1904x1200 viewport before navigation. Capture uses the existing Core `capture_locator` hierarchy and emits rendered PNG. Raw canvas readback raised `SecurityError`; captures therefore used the rendered Locator screenshot path. This output is a screenshot of the rendered canvas element, not source-native image bytes or a claim of source pixel identity. Before and after capture, the adapter checks computed display, visibility, opacity, and content-visibility for the canvas and each ancestor, along with the expected page cursor, geometry, and PNG dimensions. Hidden, translucent, changed, or unsupported output fails closed before any unverified Core fallback.

The image responses observed in the browser were decodable JPEGs matching the visible canvas dimensions, but the final response-to-visible-canvas chain is not proven. Some observed drawing calls used 50x50 source regions with differing destination offsets; that alone does not establish scrambling. Since the final mapping remains unknown and canvas readback is tainted, the implementation does not select those response bytes or attempt reconstruction/DRM work.

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

All five phases are accepted; Phase 04 review and Phase 05 Tester/final artifact audit passed with BLOCKING 0. The selected two-product live Discovery-to-ZIP route succeeded. Remaining limits are the observed horizontal layout at 1904x1200/DPR 1, rendered PNG capture with unproven source JPEG provenance, and unsupported paid/quota/resource flows. Preserve the pre-existing user edit to `watchlist.yaml` and untracked `debug.log`.

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
