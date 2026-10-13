# Phase 01 — Anonymous Site Probe and Evidence Contract

**Initial status: NOT STARTED.** [Main contract](../README.md) / [evidence ledger](../PROGRESS.md).

## Objective / inputs

Using the user-provided `https://comic-fuz.com/manga/1970?position=thumbnail`, determine a **bounded, safe, logged-out public-free** path for a work listing and one complete episode. This phase fixes v1 facts, not the later charge/ticket/medal design. Read the site-adapter guide, capture strategy, the current Zeblack/Manga ONE/Comic DAYS implementation and the relevant site notes. Examine old third-party schemas only as hypotheses; confirm against current first-party traffic.

## Evidence to collect (in this order)

1. **Identity / URLs:** allowed canonical hosts, work ID, chapter/episode ID, page URL vs viewer URL, navigation/redirect normalization, whether an episode ID is unique site-wide; derive a composite identity if uniqueness cannot be established. Treat `position=thumbnail` as a possibly decorative parameter until observed.
2. **Public listing completeness:** ordinary and expanded/next-page listings, API vs DOM, newest/oldest direction, native full count, gaps/placeholders, promotional/store items, duplicates and correct termination. Record whether full anonymous scope can genuinely be enumerated and which portions may be hidden. Determine reliable oldest→newest global position if available; do not assign a guessed position to hidden episodes.
3. **Only public free vs not-proved-free:** observe exact first-party per-episode signals for current unconditional free, explicit public expiry and non-free/unknown. Do **not** inspect or try to decode charge balance, ticket, medals, consumption or logged-in APIs for this phase. A row without a visible price/expiry, or a readable page, is not sufficient by itself. Use a second work if needed to find a verified free episode.
4. **Viewer:** whether an anonymous click enters an already-public reader with no resource prompt; first body position, img/canvas/iframe/other structure, RTL/vertical/spreads, navigation controls, readiness and stable page identity, reload/resume behavior, ad/recommendation/blank areas, last body, END and NEXT_CONTENT. Do not click a control until shown to be a non-consuming page turn.
5. **Capture source candidates:** request hosts/types and image formats, source dimensions, byte-to-page mapping, any scrambling/composition observed, source versus displayed pixels. Identify direct original JPEG/WebP/PNG if safely provable; otherwise characterize clean viewer pixels and the highest-quality lawful fallback. Do not assume inherited tile maps/obfuscation or attempt access-control/DRM bypass.
6. **Site health:** anonymous responses, pagination/access pacing and finite timeouts, error/retry cases. Inspect only bounded current-episode traffic and sanitize diagnostic artifacts (no tokens, signed image URLs, user/session state or copyrighted pages in Git).

Use shared Crawler Chrome via CDP and Playwright, single live operator. If the shared profile is actually logged in, explicitly verify the public/anonymous state without relying on the user's personal entitlements; do not log out or modify persistent credentials without authorization. A logged-out state may be established with an isolated non-persistent context only if compatible with existing browser policy and Lead approval.

## Output / checkpoint

Write observed values to `PROGRESS.md` and a small safe Phase 01 research note (under `research/` or a runbook evidence file) with fields: timestamp, work/episode URL and IDs, listed-count/coverage, exact free signal, current free sample, page/readiness/nav/END evidence, best capture candidate, hypotheses, UNKNOWNs and safety blockers. Document whether direct target-local free proof is available or a fresh series-level preflight will be required.

**Accept:** enough positive evidence to define (a) a coherent public listing/discovery contract and (b) a non-consuming free reader entry and safe capture for at least one episode. If only one subset is observable, explicitly authorize implementation of that verified subset; leave unobservable variants unsupported. Do not claim complete anonymous history without proof. If no current free target is found, build safe parsing/test contracts from observed public metadata where possible and mark the live free gate BLOCKED.

**Next:** Lead supplies a bounded Phase 02 contract and continues; charge/ticket/medal uncertainty is not a reason to pause v1.
