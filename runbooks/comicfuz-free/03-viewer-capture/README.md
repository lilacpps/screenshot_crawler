# Phase 03 — Anonymous Free Viewer and Fidelity

**Initial status: NOT STARTED.** [Main contract](../README.md) / [evidence ledger](../PROGRESS.md).

## Objective / changes

Implement `site_adapters/comicfuz/adapter.py` and only justified `access.py` / source-native capture helper(s). Reuse shared Browser Session, AccessGuard, Runner and image/Manifest contracts. The site adapter does not create Chrome profiles or raw CDP sessions. Do not assume that Manga ONE images or Zeblack protobuf imply the same current reader implementation.

## Entry and state machine

- For normal configured Batch, start with a selected Catalog target and open its **canonical episode URL directly**, if Phase 01 verified safe target-local free evidence. Otherwise do the **minimal bounded, anonymous same-work public listing preflight** first. Neither path may click entitlement/charge/ticket/medal/pay controls.
- Validate expected work and episode identity before the first capture and throughout execution; reject cross-work redirects, unrelated reader screens, expired/missing public free proof, authentication prompts and unsupported layouts. A readable page alone is not a public-free proof.
- Distinguish `LOADING`, `CONTENT`, `AD`, `END`, `NEXT_CONTENT` and `UNKNOWN` using bounded verified site signals. Seek/rewind to first body page if reader restores position, using tested non-consuming controls. Stable logical page identity and ready geometry govern page advance, not fixed sleeps or page count.
- Save full body in correct reading order, including separate right→left halves only where the renderer actually exposes a spread. Incomplete spread, missing side, mid-transition page or uncertain page identity stays LOADING/UNKNOWN; do not save an apparently half-loaded page. Exclude clearly proven ad/recommendation/blank/tail elements, not pages guessed by fixed offsets.
- The final *actual* body transition must produce verified END; changing chapter identity yields NEXT_CONTENT and must not cause capture of another chapter. If reader reaches an unknown tail or hangs, fail explicitly; incomplete ZIP/Completed is forbidden. Preserve max_pages, same-content dedupe, access pacing, bounded retries and cleanup.

## Capture and fidelity order

1. Inspect original viewer-delivered JPEG/WebP/PNG bytes. Save only with exact source-to-page identity, safe complete provenance and matching current body; preserve original bytes if verified.
2. For composited/tiled/scrambled content, only reconstruct source-derived pixels when the *current observed* draw map/geometry, source identity and output pixels can be verified. Do not assume or copy historical decoder behavior; do not bypass DRM or access restrictions. Lossless WebP or PNG is preferred for proven derived pixels.
3. If high-confidence source reconstruction is unavailable, use the clean rendered image/canvas locator with stable identity/ready checks. Screenshot is last resort; avoid UI/chrome/ad inclusion.
4. Verify reconstructed/saved dimensions, crop bounds, per-page source association and source/rendered pixel equivalence for representative cases. Do not claim original JPEG or losslessness from mere similar appearance/file size.

## Tests / exit

Unit/browser tests for malformed source identity, wrong chapter, stale free state, missing read gate, delayed/lazy viewer, page identity mutation, duplicate prevention, rewind, spreads, mid-spread loading, unknown ads/tails, END/NEXT_CONTENT, page-turn timeouts, native attribution refusal and safe fallback. For observed v1 layout(s), do one complete live anonymous free episode from first body to explicit END; visually audit first/middle/last and count/order (later verify every member in Phase 05).

**Gate:** validated free-entry path + no resource consumption + no false END/missing/duplicated/other-episode pages + bounded stop on unsupported variation. Reviewer BLOCKING 0. Record live format/dimensions and verified limitations, without treating one observed chapter as proof of all ComicFUZ variants.
