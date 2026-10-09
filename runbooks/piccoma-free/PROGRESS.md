# Piccoma free-only implementation progress

Date: 2026-10-09
Branch: `feat/piccoma-adapter`
Last committed checkpoint: `053cf79a6490e10e31089c2fc639c2c809614a59` (Phase 02)
Current status: Phase 01 accepted; Phase 02 Reviewer PASS; Phase 03 independent Reviewer PASS with BLOCKING 0. Phase 04 Site Policy/Batch and Phase 05 full Discovery-to-ZIP E2E are not started.

| Phase | Status | Evidence |
| --- | --- | --- |
| 01 Site probe | Accepted | Complete listings and conservative access signals observed for products 28600 and 28606. Viewer evidence is summarized below. |
| 02 Discovery | PASS, BLOCKING 0 | Independent review passed with 60 tests passed and 0 skipped. Commit `053cf79`. |
| 03 Viewer/Capture | PASS, BLOCKING 0 | Independent review reported 174 passed and 0 skipped. Both free seeds traversed from p1 through explicit END; first/middle/last rendered captures were inspected. |
| 04 Site Policy/Batch | Not started | No Piccoma Site Policy or quota/resource fallback exists. |
| 05 E2E | Not started | Full Discovery -> Catalog -> Batch -> Crawl -> Manifest -> ZIP is not yet verified. |

## Phase 01 listing and access evidence

The Phase 01 probes used the existing shared Crawler Chrome through BrowserSession/CDP and closed only their own pages. Phase 01 diagnostic files are sanitized metadata only; they contain no page image payloads, cookies, storage state, or signed URLs. The six Phase 03 rendered QA PNGs are separate local artifacts under ignored `output/piccoma_experiment/`; they are not committed.

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

## Remaining work and limits

Phase 03 passed independent review with BLOCKING 0. The Piccoma Policy, Batch flow, production Manifest/ZIP path, and isolated end-to-end Catalog updates are not implemented or verified yet. No Site Policy or quota/ticket/point fallback is included in this phase. Live image provenance remains unproven; rendered PNG screenshot capture is the only accepted capture mode. Preserve the pre-existing user edit to `watchlist.yaml` and untracked `debug.log`.
