# Phase 03 — Free Viewer and original-image-first capture

**Status: NOT STARTED.** Do not copy Hanayume/Younganimal geometry constants.

## Goal

Implement a site-local Viewer adapter supporting a **confirmed directly free** canonical episode, correct ordered body images and strong `END` / `NEXT_CONTENT` semantics. Keep shared Runner and standard BrowserSession/CDP unchanged.

## Entry and identity

- For a configured Batch target, bind the exact Catalog external_id, canonical episode URL, work_key and expected work ID before navigation. Prefer **one direct episode entry** if current-site proof shows it is safe and requires no grant; otherwise use a narrow, read-only, same-work preflight.
- For ad hoc/manual Crawl without Catalog target, separately obtain fresh Work/episode/access evidence before treating a route as free. Reject missing/ambiguous auth/label or redirected target.
- Do not use an interactive `無料で読む` button until Phase 01 proves it is a **non-consuming navigation**; a button with rent/wait/ticket/coin effects is always forbidden this phase.
- Detect and stop at positive login/access/paywall/rights gates, cross-episode navigation, unexpected frames, blocked API/challenge and contradictory viewer states. Never auto-spend.

## Layout and state

Identify body wrappers, first/blank/cover, ads, CI/PR/Good/Last screens, direction, seek positions and resumed-page rewind from the current viewer. Prove strict role mapping and stable page fingerprints/counts before capture. Support only actually observed layout variants, with safe fail-closed unknowns. Preserve split body, single-page/spread and both halves in reading order. Bounds on wait, page-change retries, max_pages and unchanged fingerprints. A final body page alone is not evidence of completed END: verify actual terminal signal.

## Fidelity strategy and proof order

1. Inspect **first-party naturally emitted** image response bytes and match unique exact episode/page/source identity and visible complete body-page pixels; retain unchanged JPEG/WebP/PNG bytes if valid.
2. If scrambled JPEG has complete verified block permutation and MCU/DCT constraints, test optional lossless coefficient reconstruction using existing BookWalker/Jump+ patterns. Do not resave a scrambled stream as the page. Stop researching that branch when not provable in the bounded investigation.
3. Snapshot exact source pixels from `ImageBitmap`/canvas/draw-time sources when justified. Reproduce tile transforms/crops/filters/alpha and verify selected source→Viewer mapping; require pre/post selection stability and decoded-RGBA equality after **lossless WebP** encoding. Keep valid native PNG if WebP verification fails.
4. Fallback to stabilized **rendered body canvas PNG**; if direct canvas access impossible, body Locator screenshot PNG, and only last resort viewport screenshot. No UI/ads in body output, no blank/spread-half omissions.

No costly synchronous encodes or hashes in renderer hooks; bounded candidate retention and release, no unsafe network observer that blocks page rendering. Original-byte and source-native proof are distinct. If a viewer image is rescaled, validate source-native pixels independently plus the renderer transform; naïvely compare dimensions without transformation only when equal.

## Tests / exit

- Synthetic browser fixtures for free entry, denied/stale access, redirects, first/middle/last, delayed initial canvas, seek resume, 1-body/spread, blank/ads, changing draw generation, unknown role, duplicate/missing page, no stable END and stalled navigation.
- Unit tests for URL/identity and capture bytes/dimensions/format, failed native proof to PNG, source pixel/decoded WebP equality, no post-proof races, no accidental `quota` execution.
- Live bounded 1–2 free episodes with sampled first/middle/final body pages and terminal END. Audit actual per-page format, dimensions, fingerprint, visual crop/reading order and provenance; confirm chosen native mapping on every native saved page.
- Reviewer must verify **no false-original claim** and safe, independent PNG fallback. Unresolved native optimization alone need not block correct PNG E2E, but record exact reason and follow-up.

Update PROGRESS and site documentation. Continue to Phase 04.
