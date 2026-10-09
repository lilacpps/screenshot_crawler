# Piccoma current implementation snapshot

Updated: 2026-10-09. Phase 01 evidence is accepted; Phase 02 Discovery and Phase 03 Viewer/Capture passed independent review (Phase 03 BLOCKING 0). Phase 04 Piccoma Site Policy/Batch and Phase 05 full E2E remain unimplemented.

## Current adapter and CLI registration

`PiccomaDiscoveryAdapter` is registered with Discovery. `PiccomaAdapter` is registered in the manual crawl and Batch adapter registries. Registration provides the viewer adapter implementation; it does not supply a Piccoma Site Policy or make the full Batch path available. Manual adapter entry supports only `auto` and `direct`, both bound to the same freshly verified unconditional-free path. Quota, paid, unknown, and unsupported states stop without fallback.

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

At viewer initialization, the adapter obtains the product listing again and requires the target composite row to remain uniquely present and exact-free. It then navigates to the canonical viewer and requires HTTP 200 and the same product/episode identity. Redirects, quota/paid/unknown status, duplicate/missing rows, and unexpected dialogs fail closed. It does not use tickets, points, coins, waiting, purchases, rentals, unlocks, or access-control bypass.

On the 2026-10-09 snapshot, product 28600 exposed 432/432 exact-free rows. Product 28606 exposed 12 exact-free rows, 167 wait/binge-free rows, and 39 point-priced rows. These are observations, not constants. Seeds 28600/1910027, 28600/4142286, and 28606/2001009 appeared at native DOM indices 0, 421, and 1 respectively.

## Viewer state and navigation

The live-supported layout has root `#react_ViewerApp`, body classes `PCM-stt_horizontal` and `PCM-prop_scroll_l`. The page list is `#react_PageListApp`; its frame is `#js_frame.PCM-viewer2_frame`. Body wrappers have unique contiguous IDs `p1..pN` followed by one `last` wrapper. The observed page sequence was p1 through pN via the in-episode next control; native DOM wrapper order is reversed. These facts do not infer additional semantics from the `PCM-prop_scroll_l` class. Unknown layouts, missing IDs, duplicates, and non-contiguous page sets fail closed.

A body page is considered loaded only when its expected ID is the sole active page, the page has exactly one canvas and one loaded canvas wrapper, the canvas and every ancestor are displayed and visible with opacity 1 and content-visibility visible, and canvas viewport/backing geometry remains stable over three samples. After p1 normalization, the expected cursor advances only after the adapter uses the in-episode next control and verifies the exact next page ID. Unrequested jumps and rewinds are UNKNOWN. END is valid only after advancing from pN to active `last` with `#js_viewerEnd`; no next-episode control is clicked.

One late resume prompt was observed. After a bounded 1.5-second attachment grace, the adapter cancels only the unique observed dialog with exact prompt shape/text, two expected enabled buttons, and no link. Besides the numeric-page wording, the exact observed last-page wording is `前回最後のページを 読んでいました。 最後のページに移動しますか？`; mixed numeric/last-page wording or extra text is rejected. A different or ambiguous dialog aborts. The unique #js_scrollTypeSing reading-direction guide is hidden during capture only after validating one of the two observed exact root class sets (base class alone, or base plus `_sh` and `_show`), the same two child groups, three expected image labels/classes, lack of meaningful text/interactive nodes, and empty pseudo-element content; its original inline style and visible state are restored. Unknown or duplicate guide markup aborts.

## Capture path and provenance

Before navigation, the owned Page viewport is set to 1904x1200, the observed supported layout. Before and after each capture the adapter verifies the same viewer identity, expected page cursor, active page ID, loaded canvas, computed display/visibility/opacity/content-visibility on the canvas and every ancestor, frame/canvas geometry, viewport, and PNG dimensions. A hidden or translucent canvas, cursor change, geometry change, or identity change fails closed without entering an unverified Core fallback.

Capture calls Core `capture_locator` on the current body canvas. This preserves the Core capture hierarchy. Live canvas `getImageData` raised `SecurityError`; the accepted capture mode is therefore the rendered Locator screenshot PNG. This is rendered screenshot output, not source-native image data, even where output and canvas dimensions match. Live captures were 844x1200 for product 28600 and 842x1200 for product 28606.

Browser-observed image responses were decodable JPEGs matching visible canvas dimensions, but exact response-to-visible-canvas attribution remains unproven. Some draw calls used 50x50 source regions with differing destination offsets. That observation alone does not prove scrambling; the final visible chain remains unknown. The adapter does not use those response bytes, alter canvas security/backing settings, or attempt reconstruction.

## Live verification and artifacts

On 2026-10-09, after the Reviewer fixes, each seed was rechecked as exact-free in its current listing, entered at the requested viewer path, traversed from p1 through every page to explicit active END, and captured at first/middle/last. Product 28600/1910027 had 24 body pages and captures p1/p12/p24 (844x1200). Product 28606/2001009 had 15 body pages and captures p1/p8/p15 (842x1200). Both viewer paths were unchanged at END. The reading guide was visible before and after all six captures. All six latest ignored PNGs were visually inspected; the body filled the frame sharply without reader chrome. The Lead also inspected product 28600 p1.

Phase 01 evidence files are sanitized metadata only and contain no image payloads. The Phase 03 rendered QA PNGs remain local ignored artifacts in `output/piccoma_experiment/`; their summary is `phase03_b_live_capture_evidence.json`. No image payloads, browser state, cookies, or signed URLs are committed.

## Tests and remaining scope

Phase 02 independent review: 60 passed, 0 skipped, BLOCKING 0. Phase 03 independent review: PASS, BLOCKING 0, 174 passed, 0 skipped. The focused implementation run also passed 174 tests with 288 pytest-asyncio event-loop-policy deprecation warnings. `ruff check src tests` passed. Browser-fixture tests cover entry and identity guards, delayed/exact/unknown dialog handling, complete/partial/duplicate readiness, transitions, unapproved jump/rewind rejection, END, guide restoration, canvas/ancestor visibility before and after capture, geometry, and PNG format/dimensions; guide checks reject appended text and unknown elements.

The full route `Discovery -> Catalog -> Batch -> Crawl -> Manifest -> ZIP`, dedicated Site Policy behavior, production Catalog updates through Batch, and ZIP contents remain unverified. The two-seed live test verifies viewer/capture only. Phase 03 passed independent review; Phase 04 has not started.
