# Piccoma free-only implementation progress

Date: 2026-10-09
Branch: `feat/piccoma-adapter`
Checkpoint commit: `1d018503`
Status: Phase 01 listing/access evidence accepted; Phase 02 Reviewer PASS / BLOCKING 0; bounded Phase 03-A live probe in progress. Capture contract, Batch, and E2E remain NOT VERIFIED.

## Phase status

| Phase | Status | Checkpoint |
| --- | --- | --- |
| 01 Site Probe | Accepted for Discovery evidence | Complete native-list and current listing access signals observed for products 28600 and 28606. Viewer entry, controls, image mapping, and END deferred to Phase 03 probe. |
| 02 Discovery | PASS; BLOCKING 0 | Reviewer independently passed with 60 tests passed and 0 skipped; final URL checks, wrapper marker inspection, Catalog access refresh are included. |
| 03 Viewer/Capture | Phase 03-A live probe in progress | Two exact-free seeds rechecked before viewer navigation; roots, paging controls, END container, canvas and JPEG observations captured. No transitions yet. |
| 04 Direct-only Policy/Batch | Not started | Depends on Phase 03 current-access evidence. |
| 05 E2E | Not started | Requires Phases 02–04 and review gates. |

## Phase 01 live evidence

Used the existing shared Crawler Chrome at the default CDP endpoint through
`BrowserSession`. The bounded probe created and closed only its own Page and
disconnected without closing Chrome. Probe code and sanitized output are in
ignored `output/piccoma_experiment/phase01_probe.py` and
`phase01_listing_evidence.json`; no image payloads, cookies, storage state,
signed URLs, or raw HTML were saved.

On 2026-10-09, both listing pages returned HTTP 200 and exposed one
`#js_episodeList.PCM-list_asc` list. Every row has a containing anchor with
`data-product_id` and `data-episode_id`, one episode title, and one status
wrapper. The live list size matched its visible `全N話` count, all IDs were
unique, all row product IDs matched the page, and all titles were non-empty.
Native DOM order is oldest-to-newest; the adapter reverses it for the generic
Discovery service and carries global position as original DOM index + 1.

| Product | Declared/listed | Status distribution | Provided viewer seeds in DOM |
| --- | ---: | --- | --- |
| 28600 | 432 / 432 | 432 nested `PCM-epList_status_free` with exact `¥0` | 1910027 index 0; 4142286 index 421 |
| 28606 | 218 / 218 | 12 exact free; 167 `waitfree` + `bingefree`; 39 point marker with `69` | 2001009 index 1 |

The page body displayed login/register controls and the logout body state. Every
row also had `data-user_access=require`; that attribute is not treated as free
evidence. The adapter collects prefixed status markers from the status wrapper
and descendants. Only the exact marker set `PCM-epList_status_free` plus exact
visible `¥0` maps to `free`; wrapper/descendant conflicts map to `unknown`.
Observed wait-free maps to `quota`, positive integer point price maps to `paid`,
and other states map to `unknown`. Current counts are evidence snapshots, not
implementation constants.

## Phase 02 implementation checkpoint

Added Piccoma-local strict viewer URL parsing, product-scoped
`product_id:episode_id` source identity, complete-list buffering/validation,
status classification, latest-first iteration, inclusive site-native bounds,
and unchanged whole-work display positions. The existing Discovery service
continues to own Catalog writes and full/incremental behavior. No Core, Catalog
schema, Site Policy, or Batch code was changed.

The independent Reviewer returned two BLOCKING findings: final listing URL
validation omitted scheme/userinfo/port checks, and marker collection omitted
the status wrapper itself. Both are fixed. Integration coverage also re-discovers
the same source through free → paid → quota → unknown and confirms access state
updates while completed Item status is retained. Targeted Unit + browser-fixture
and affected Discovery / CLI tests passed: 190 passed, 689 warnings, 0 skipped.
`ruff check src tests` and `git diff --check` passed. Warnings are existing
pytest-asyncio event-loop-policy deprecations. Re-review is pending; Phase 03
must not start before the Lead accepts these fixes.

## Phase 03-A live probe checkpoint

On 2026-10-09, product/episode listing membership and current exact-free status
were rechecked before direct viewer navigation for 28600/1910027 and
28606/2001009. Both viewer URLs returned HTTP 200 on the requested identity in
the logged-out state. The viewer root is `#react_ViewerApp`; body classes include
`PCM-stt_horizontal` and `PCM-prop_scroll_l`. The page strip uses
`#react_PageListApp.PCM-viewer2_wrapper`, `#js_frame.PCM-viewer2_frame`,
`.PCM-viewer2_pagesWrap`, `.PCM-viewer2_pageWrapper`, and
`.PCM-viewer2_canvasWrapper`. In-reader controls are the separate
`button.PCM-viewer2_pagingBtn_next` and `button.PCM-viewer2_pagingBtn_prev`.
The explicit end container is `#js_viewerEnd.PCM-viewer2_endPage`; its
`.PCM-viewer2ReadBtn` is a distinct next-episode action and has not been used.

Initial layout mounted six adjacent canvas nodes per seed, each 842/844 by 1200
pixels. Direct `getImageData()` on these canvas nodes raises `SecurityError`.
Associated image responses observed in the browser are decodable JPEGs at the
same dimensions, but source-response-to-page/canvas identity and pixel equality
remain unproven. No reader control has been clicked yet. Bounded sanitized
metadata is in ignored `output/piccoma_experiment/phase03_a_initial.json`;
no response query strings or image payloads were saved.

## Unverified and next action

The three sample viewers have not been entered in this checkpoint. Therefore
viewer entry safety, current-access revalidation, viewer page structure,
readiness, page navigation, source response mapping/format, rendered canvas,
page count/order, and terminal END are NOT VERIFIED. No paid, ticket, wait,
point, purchase, rental, unlock, or next-episode action has been performed.

Next: with exact-free state rechecked, test only the two in-reader paging buttons
under the 60-transition-per-seed bound, identify first/middle/last body pages and
END without touching the next-episode CTA, and prove or reject source-to-canvas
identity. Preserve the pre-existing `watchlist.yaml` edit and untracked `debug.log`.
