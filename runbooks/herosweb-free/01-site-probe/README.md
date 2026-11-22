# Phase 01 — HERO'S WEB current-site evidence probe

**Status: NOT STARTED.** Read [parent contract](../README.md) and [PROGRESS](../PROGRESS.md). Browser evidence must be from post-2026-06-01 `https://heros-web.com/`; legacy `viewer.heros-web.com` is not the target.

## Goal

Resolve the few site-specific facts that prevent safe coding. Use an existing shared Crawler Chrome/Playwright Page and bounded **read-only/free** interactions. This phase may hand off partially verified subcontracts directly into Phase 02/03; do not assume the entire website needs reverse engineering before coding.

## Initial samples

1. User-confirmed candidate `https://heros-web.com/series/fdf345d17d2b6` (「はんばけ」). Confirm canonical route, page title, work ID, and current row links in browser.
2. Another **observed current** work with directly free episodes, if available. Choose an episode that exercises another viewer layout or a longer listing.
3. Examples of a nonfree ticket/wait and paid-only row for **read-only classification**; do not attempt entry or press a control that obtains rights.

`/seriesh/` was a mistaken prior suggestion. Reject it as an unsupported URL; no automatic typo-correction rule without a verified current-site conversion.

## Read-only questions / proof

- **URL/identity:** exact canonical work and episode path, domain/redirect, stable source IDs, relation from episode to work, work-level ID uniqueness, pagination/range URLs, apparent (opaque) ID format.
- **Inventory:** how to expand all episodes (range pages vs loader); displayed total/ranges, hidden lazy rows, list order, special episodes, split/repeated titles, duplicates, and trustworthy termination signal. Plan bounded upper limits and pacing.
- **Access:** exact row-scoped labels and DOM/API attributes, logged-out/positive logged-in evidence if available, `free` direct-read test, `quota` and `paid` *read-only* evidence, contradictions, active grants and expiry. Do not infer from similar sites; avoid account-state changes.
- **Viewer:** canvas/img/read mode, 1-page/spread, initial blank/advertising, wrapper and seek/counter roles, first→middle→last, resumed seek rewind, render stabilization, page identity, `END`, `NEXT_CONTENT`, UI overlay/blocked states.
- **Image:** record safe metadata for naturally emitted responses (MIME, dimension, number of tiles, source-to-draw association) and whether exact finished original-page bytes exist; if scrambled, test whether a verifiable lossless JPEG path or native source-canvas snapshot is plausible. Compare legitimate sample with displayed body pixels; no downloaded content in tracked fixtures.
- **Performance/safety:** bounded requests, rate-limit observations, response failures, cleanup, mutating requests accidentally triggered by passive page navigation. Handle 403/429/challenge as stops, not signals to retry harder.

## Required checkpoint

Write OBSERVED / HYPOTHESIS / UNKNOWN / BLOCKED findings into `PROGRESS.md`, including sample canonical routes (without signed query or tokens), row labels and provenance, layout variants, and viable capture paths. Separate verified non-consuming Viewer entry from simply displaying `無料`. Reviewer independently checks permissions, identity, viewer signals and provenance.

**Exit:** enough affirmative evidence to implement the first full-listing path and one free Viewer path, or a precise external blocker. No ticket/coin/wait/rental mutation; no fabricated E2E result.
