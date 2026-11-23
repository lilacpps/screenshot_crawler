# Phase 03 — Free Viewer and original-image-first capture

**Status: PASS / BLOCKING 0 for A10 and B14 full native profiles.** A10 passed independent full-capture audit with 10/10 lossless VP8L pages at 1440x2048; B14 passed with 38/38 lossless VP8L pages at 844x1200. Both matched retained source-PNG RGBA, reached actual END and passed ZIP/Catalog integrity. B14 also verified exact tile history, replay, stability and page order. B10 was an earlier full rendered-PNG run; B11 and B13 were bounded diagnostics whose limitations are historical and retained below. The B12 resumed-loading profile and synthetic regressions remain bounded to the observed layouts. Original JPEG recovery remains unproven. Do not copy Hanayume/Younganimal geometry constants.

Current live profiles and independent artifact audits:

- `dca88b215773f` / `4fe9831c6f540`: 17 wrappers, 10 body slots, fresh plain-free proof, 10/10 VP8L pages at 1440x2048, terminal seek 1 / Last wrapper 16, audited ZIP.
- `0f023839d7bca` / `b92706d1ebe2e`: 45 wrappers, 38 body slots, fresh authenticated same-Work free proof, 38/38 VP8L pages at 844x1200, terminal seek 1 / Last wrapper 44 after body coverage, audited ZIP.

Both current audits verified manifest/ZIP order, CRC, exact decoded RGBA against retained source-PNG proofs, body-slot/spread order, full source-tile history/replay/stability and terminal coverage. Original JPEG-byte fidelity remains unproven. Earlier Phase 03/05 PNG runs, B10 rendered capture and B11/B13 bounded diagnostics are historical checkpoints superseded by A10/B14; their evidence and limits remain in [PROGRESS.md](../PROGRESS.md).

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
