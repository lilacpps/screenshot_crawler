# Piccoma adapter

## Implemented scope

Piccoma Discovery and the free-only horizontal viewer/Capture adapter are implemented. The Discovery adapter validates complete product episode lists and classifies access conservatively. The viewer adapter rechecks the target's current listing state before entering the viewer and captures rendered body pages through the existing Core capture helper.

Phases 03 and 04 passed independent review with BLOCKING 0. Phase 05 independently verified full and incremental Discovery, direct-only planning, and the real standard Batch-to-ZIP path for one current free episode from each product. Tester and artifact audit passed; the final independent evidence/design review passed with BLOCKING 0. Detailed results and limits are recorded below and in [runbook progress](../../../../runbooks/piccoma-free/PROGRESS.md).

## Discovery and identity

Watchlist targets use a canonical HTTPS viewer URL:

```text
https://piccoma.com/web/viewer/{product_id}/{episode_id}
```

Discovery opens the matching `/web/product/{product_id}/episodes` listing. It buffers and validates the complete list before yielding: declared and observed counts must match, the product heading and every row must match the requested product, IDs must be unique numeric values, titles and status wrappers must exist, and the target episode must be present. Native DOM order is oldest-to-newest. Discovery yields latest-to-oldest and assigns whole-work display position as original DOM index + 1 before inclusive bounds are applied. Source identity is `{product_id}:{episode_id}`; caller-owned `work_key` does not encode product identity.

## Access classification

Unconditional free requires exactly one `PCM-epList_status_free` marker across the status wrapper and descendants plus exact visible `¥0`. Conflicting markers map to unknown. A recognized wait-free status maps to quota, a positive point price maps to paid, and ambiguous/missing signals remain unknown. Personal readability and generic status labels do not prove unconditional free access.

At viewer initialization, the adapter opens the product listing again and confirms that the exact target still has the free marker and exact zero price. It then requires HTTP 200 at the requested product/episode viewer path. `auto` and `direct` use this same fresh-free route; quota and other unsupported access strategies stop without fallback. The caller's work key is retained as opaque metadata.

## Batch policy

The registered `PiccomaSitePolicy` admits a source only when Catalog says `available=true` and `access_mode=free`. It returns `direct` with reason `free`; quota, paid, owned, grant, rental, unknown, and unavailable sources are rejected regardless of grant timestamps. A grant timestamp does not disqualify a source that remains available and classified as free. The policy exposes no quota/access resources, grant-only support, or additional passes. The generic Planner retains Catalog ordering, composite source identity, whole-work display position, and metadata. Standard Batch execution still performs stale-candidate validation and the adapter's fresh exact-free listing check before viewer entry.

A local Playwright fixture test exercises the standard Planner, `BatchExecutor`, `CrawlerRunner`, adapter, manifest, packager, and Catalog completion path using a synthetic three-page episode. Failure fixtures cover stale-free state, a wrong composite candidate identity, and a redirected viewer; they assert no ZIP, no completed Item/Artifact, and no quota/resource mutation. This covers the local integration contract; Phase 05 separately verified the real live Batch path for one currently free episode from each product.

## Viewer and capture

The supported observed reader is horizontal and has body classes `PCM-stt_horizontal` and `PCM-prop_scroll_l`. Body wrappers must form a complete contiguous `p1..pN` list, with one additional `last` wrapper. The observed page sequence was p1 through pN using the in-episode next control; native DOM wrapper order is reversed. A page is ready only when its expected ID is uniquely active and its single canvas is loaded, stable, and fully visible through every ancestor. The adapter advances only through the in-episode next control and waits for each expected ID. It accepts terminal END only after advancing from pN to the active `last` wrapper containing `#js_viewerEnd`.

An exact known resume prompt may be canceled after validating its structure, text, and two expected enabled buttons. The observed prompt variants are the numeric-page wording and the exact last-page wording (`前回最後のページを 読んでいました。 最後のページに移動しますか？`); mixed wording or extra text is rejected. Attachment is bounded; unknown/ambiguous dialogs fail closed. The one known non-interactive #js_scrollTypeSing reading-direction guide is hidden only for capture after validating one of the two observed root class sets (base class alone, or base plus `_sh` and `_show`), the same exact two child groups and three expected image labels/classes, lack of meaningful text/interactive nodes, and empty pseudo-elements; its prior inline style is restored afterward.

The owned Page starts at 1904x1200 before navigation. Captures use the Core `capture_locator` hierarchy and are labeled rendered PNGs. Live canvas raw readback raised `SecurityError`, so current captures use the rendered canvas Locator screenshot fallback. Before and after capture, the adapter checks computed display, visibility, opacity, and content-visibility on the canvas and all ancestors, as well as the expected page cursor and unchanged geometry. Hidden, translucent, or changed output fails closed. The image response-to-visible-canvas mapping is not proven; the adapter does not substitute observed JPEG responses or attempt image reconstruction. Actual canvas and PNG dimensions must agree.

## Live evidence and limits

On 2026-10-09, after the Reviewer fixes, the current listings for 28600/1910027 and 28606/2001009 each showed one exact-free target row (`PCM-epList_status_free`, `¥0`). The viewer path stayed on the requested composite identity. Product 28600 had 24 body pages; p1, p12, and p24 were captured as 844x1200 PNGs before explicit active END. Product 28606 had 15 body pages; p1, p8, and p15 were captured as 842x1200 PNGs before explicit active END. The reading guide was present and restored after each capture. All six latest ignored diagnostic PNGs were visually inspected. Sanitized evidence is under ignored `output/piccoma_experiment/phase03_b_live_capture_evidence.json`.

Phase 05 verified the live route `Discovery -> Catalog -> Batch -> Crawl -> Manifest -> ZIP` for 28600/1910027 and 28606/2001009. Both targets were freshly observed as free before entry, stayed on the requested URL, reached explicit END, and produced ordered unique body pages. The 24-page 28600 ZIP contains 24 manifest members at 844x1200; first/middle/last visual checks were p1/p13/p24. The 15-page 28606 ZIP contains 15 members at 842x1200; checks were p1/p8/p15. CRC, exact membership, capture hashes, Catalog Artifact hashes, completed Items and succeeded END runs passed independent audit. First/middle/last images for both episodes were visually checked. Image SHA256 audits were unique across all 24 and 15 pages, with zero duplicate groups. See ignored `output/piccoma_experiment/phase05_tester/evidence/phase05_tester_report.json` and `phase05_final_independent_audit.json`; these local reports and image/ZIP artifacts are not committed.

This validates the observed horizontal layout at a 1904x1200 viewport and DPR 1. Other viewer layouts/resources remain unsupported. Capture is rendered PNG (`source_native=false`); exact source JPEG-to-canvas provenance remains unproven. Catalog `last_seen_at` was populated, but `access_checked_at` remained NULL after live free-entry verification. Redirected Windows CLI output for `batch plan` initially failed under cp932 on title U+8E20; rerunning with task-local `PYTHONIOENCODING=utf-8` and `PYTHONUTF8=1` passed without title loss or code changes. No ticket, waiting, point, purchase, rental, unlock, CAPTCHA bypass, or DRM bypass flow was used.

## Tests

Phase 03 review passed with BLOCKING 0 (174 passed, 0 skipped). Phase 04 review passed with BLOCKING 0 (130 passed, 0 skipped); local policy/CLI tests passed (96), Piccoma Batch browser integration passed (34), and the combined affected suite passed (310, 0 skipped). Phase 05 live Tester E2E and final audit passed. The full local suite passed 1827 tests, 0 skipped; `ruff check src tests` passed. Live browser access used shared Crawler Chrome via existing CDP/BrowserSession integration. No copyrighted payloads or authentication data were committed.
