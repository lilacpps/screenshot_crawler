# Piccoma adapter

## Implemented scope

Piccoma Discovery and the free-only horizontal viewer/Capture adapter are implemented. The Discovery adapter validates complete product episode lists and classifies access conservatively. The viewer adapter rechecks the target's current listing state before entering the viewer and captures rendered body pages through the existing Core capture helper.

Phase 03 Viewer/Capture passed independent review with BLOCKING 0. The Piccoma Site Policy, full Batch orchestration, and production Manifest/ZIP end-to-end flow are not implemented or verified yet; Phase 04 and Phase 05 remain open.

## Discovery and identity

Watchlist targets use a canonical HTTPS viewer URL:

```text
https://piccoma.com/web/viewer/{product_id}/{episode_id}
```

Discovery opens the matching `/web/product/{product_id}/episodes` listing. It buffers and validates the complete list before yielding: declared and observed counts must match, the product heading and every row must match the requested product, IDs must be unique numeric values, titles and status wrappers must exist, and the target episode must be present. Native DOM order is oldest-to-newest. Discovery yields latest-to-oldest and assigns whole-work display position as original DOM index + 1 before inclusive bounds are applied. Source identity is `{product_id}:{episode_id}`; caller-owned `work_key` does not encode product identity.

## Access classification

Unconditional free requires exactly one `PCM-epList_status_free` marker across the status wrapper and descendants plus exact visible `¥0`. Conflicting markers map to unknown. A recognized wait-free status maps to quota, a positive point price maps to paid, and ambiguous/missing signals remain unknown. Personal readability and generic status labels do not prove unconditional free access.

At viewer initialization, the adapter opens the product listing again and confirms that the exact target still has the free marker and exact zero price. It then requires HTTP 200 at the requested product/episode viewer path. `auto` and `direct` use this same fresh-free route; quota and other unsupported access strategies stop without fallback. The caller's work key is retained as opaque metadata.

## Viewer and capture

The supported observed reader is horizontal and has body classes `PCM-stt_horizontal` and `PCM-prop_scroll_l`. Body wrappers must form a complete contiguous `p1..pN` list, with one additional `last` wrapper. The observed page sequence was p1 through pN using the in-episode next control; native DOM wrapper order is reversed. A page is ready only when its expected ID is uniquely active and its single canvas is loaded, stable, and fully visible through every ancestor. The adapter advances only through the in-episode next control and waits for each expected ID. It accepts terminal END only after advancing from pN to the active `last` wrapper containing `#js_viewerEnd`.

An exact known resume prompt may be canceled after validating its structure, text, and two expected enabled buttons. The observed prompt variants are the numeric-page wording and the exact last-page wording (`前回最後のページを 読んでいました。 最後のページに移動しますか？`); mixed wording or extra text is rejected. Attachment is bounded; unknown/ambiguous dialogs fail closed. The one known non-interactive #js_scrollTypeSing reading-direction guide is hidden only for capture after validating one of the two observed root class sets (base class alone, or base plus `_sh` and `_show`), the same exact two child groups and three expected image labels/classes, lack of meaningful text/interactive nodes, and empty pseudo-elements; its prior inline style is restored afterward.

The owned Page starts at 1904x1200 before navigation. Captures use the Core `capture_locator` hierarchy and are labeled rendered PNGs. Live canvas raw readback raised `SecurityError`, so current captures use the rendered canvas Locator screenshot fallback. Before and after capture, the adapter checks computed display, visibility, opacity, and content-visibility on the canvas and all ancestors, as well as the expected page cursor and unchanged geometry. Hidden, translucent, or changed output fails closed. The image response-to-visible-canvas mapping is not proven; the adapter does not substitute observed JPEG responses or attempt image reconstruction. Actual canvas and PNG dimensions must agree.

## Live evidence and limits

On 2026-10-09, after the Reviewer fixes, the current listings for 28600/1910027 and 28606/2001009 each showed one exact-free target row (`PCM-epList_status_free`, `¥0`). The viewer path stayed on the requested composite identity. Product 28600 had 24 body pages; p1, p12, and p24 were captured as 844x1200 PNGs before explicit active END. Product 28606 had 15 body pages; p1, p8, and p15 were captured as 842x1200 PNGs before explicit active END. The reading guide was present and restored after each capture. All six latest ignored diagnostic PNGs were visually inspected. Sanitized evidence is under ignored `output/piccoma_experiment/phase03_b_live_capture_evidence.json`.

These two live seeds verify the observed viewer and capture contract only. They do not verify full Batch, Catalog refresh through Batch, Manifest/ZIP output, other viewer layouts, or source-native image provenance. Phase 01 diagnostics are metadata-only; Phase 03 rendered QA PNGs remain ignored local artifacts and are not committed. No ticket, waiting, point, purchase, rental, unlock, CAPTCHA bypass, or DRM bypass flow is implemented.

## Tests

Focused browser-fixture and affected Discovery/Catalog/CLI tests passed: 174 passed, 288 pytest-asyncio event-loop-policy deprecation warnings, 0 skipped. Independent Phase 03 review passed with BLOCKING 0 (174 passed, 0 skipped). `ruff check src tests` passed. The live probe used shared Crawler Chrome via the existing CDP/BrowserSession integration; it did not launch a browser or commit copyrighted payloads.
