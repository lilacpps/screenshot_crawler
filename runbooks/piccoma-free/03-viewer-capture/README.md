# 03 — Free Viewer / Capture

Status: PASS, BLOCKING 0 (174 passed, 0 skipped). Live viewer/capture evidence: [PROGRESS](../PROGRESS.md).
Explorer researches unknown variants; Implementer writes; Reviewer gates;
Tester independently checks tricky captures when needed.

## Objective and scope
Add piccoma/adapter.py and only justified site-local access or native_capture
helpers. Preserve common Core Runner, Browser Session, Capture Strategy,
manifest and packaging; no generic refactor without explicit Lead gate.

## Behavior
- Configure auto as safely direct-only (if accepted) and explicit direct;
  reject quota and quota resources. Validate Catalog external ID, target URL,
  live product/episode identity and **current genuinely free entitlement**
  prior to saving any body page. A stale Catalog free is insufficient.
- Never click a ticket, ¥0+, charge, pay, login, rental or unlock CTA;
  personal active access does not qualify as unconditional free. Wrong target,
  redirect, unsupported UI and access wall fail closed.
- Detect exact supported viewer types, start/rewind to the first body page
  with bounded verified controls if reading position persists. Avoid fixed
  sleeps as the only change signal; use stable page identity and readiness.
- Represent CONTENT, LOADING, AD, END, NEXT_CONTENT and UNKNOWN from
  observed page structure. Incomplete spreads remain loading/unknown; no
  single-half capture. END follows final body with explicit evidence,
  no implied auto-navigation into the next paid episode.
- Capture priority: exact original bytes with proven identity → attributable
  source-native pixels → rendered canvas → Locator screenshot. Preserve
  native JPEG/WebP/PNG. Treat scrambled/composited/encrypted resources as
  **not native** without a separately validated safe method; never bypass
  DRM or access controls. No lossy conversion as a fidelity improvement.
- Preserve max_pages, same-content, bounded retries, AccessGuard/pacing,
  progress and manifest contracts.

## Tests / acceptance
Unit tests for wrong target, stale free, forbidden clicks, state machine,
page identity, timeout, duplicate prevention, END, source-provenance checks.
Browser integration for first/last, rewind, lazy loading, horizontal/vertical
if supported, multi-page spread ordering, ads/unknown, wrong-next-content
and render fallback. Perform a live free episode crawl, checking each saved
page against visible content, image count, reading order and terminal state.

Gate: no silent missing/duplicate page, false END, non-free access or
unsound original-byte attribution. Reviewer zero BLOCKING. If no verified
free episode is available, mark live verification blocked, not passed.
