# Hanayume Site Adapter

Status: Discovery, manual Viewer capture, and direct-only Batch integration are implemented on `feat/hanayume-adapter`. Phases 01-05 passed independent review in the user-authorized logged-out `無料` scope. Final Reviewer PASS / BLOCKING 0: 42 fresh tests, 0 skipped, Ruff/diff, and independent SQLite/ZIP/PNG artifact audits passed. The Tester completed three episodes and 122 body pages into three verified ZIP Artifacts; all 122 same-run canvas PNGs matched exactly and 9/9 sampled pages passed visual review. `今なら無料` remains `unknown` and ineligible under the no-login scope.

## Discovery

Watchlist targets use the strict episode URL `https://hanayume.com/episodes/<13-lowercase-hex-id>`. Discovery reads each declared numbered range, validates the complete same-work range set and rows, buffers the full list, assigns global oldest-first positions, then yields latest-first or applies inclusive bounded scope. Missing, duplicate, foreign, inconsistent, or incomplete rows fail closed.

Only exact row-scoped labels are classification evidence:

- `無料` maps to `access_mode=free`.
- `今なら無料` maps to `access_mode=unknown` pending authenticated, non-consuming verification.
- Missing, duplicate, conflicting, and other labels map to `access_mode=unknown`.

Catalog stores `access_mode`; it does not persist the raw label. The confirmed scope is logged out, so `今なら無料` is not eligible for Viewer capture or Batch. No login, registration, purchase, ticket, coin, point, or other entitlement action is part of this adapter.

## Viewer capture

The manual `crawl --site hanayume` path accepts an exact episode URL. Before entry, the adapter verifies the scoped work identity, exact bare same-work URL, and finite range set. It first checks the bare listing for one exact target row; if absent, it follows observed numbered routes, validates each exact selected range and complete page-local row set, and stops at the first unique target. Ambiguous/duplicate/nonfree target rows fail immediately, and all ranges are exhausted only when the target is absent. On the exact episode page it checks the scoped work and one exact `無料` label again. Discovery retains responsibility for full-work coverage and global uniqueness.

The adapter supports only the observed desktop spread layout. It explicitly rewinds with the public seek control, treats a wrapper as active only when its center lies in the viewport, requires each selected body canvas to be loaded and rendered under its own page wrapper, captures the selected canvas atomically as PNG, and checks body slots in order through the final body page. A previous wrapper with only a 15.33 px viewport sliver is excluded even when its canvas is offscreen. Any ambiguous wrapper, active loading spread side, missing spread half, readback error, or premature terminal marker fails closed. Terminal UI is accepted only after all body slots were captured. Hanayume disables generic locator/screenshot capture fallback.

The production capture stores the rendered body-canvas PNG. It preserves the selected canvas's pixel dimensions and rendered pixels, but does not preserve the higher-resolution 960×1540 JPEG source pixels. A bounded source-native replay proof covered only one page and did not establish a reusable per-page mapping. The tested 240×385 tile geometry also rejects the measured MCU-8 DCT permutation approach. No screenshot containing viewer UI or adjacent promotion is used as page output.

## Batch policy and execution

`HanayumeSitePolicy` admits only available sources with exact `access_mode=free`, using the `direct` strategy. It rejects `unknown`, `quota`, `paid`, `owned`, `grant`, and `rental`, even when grant timestamps exist. No quota resource or grant-only pass is supported. Batch uses the existing Planner, Executor, Runner, and Packager. Each run performs a fresh identity and exact `無料` badge preflight; a row that has changed to `今なら無料` stays ineligible. Failed runs do not create a ZIP Artifact or complete the Item.

The local synthetic browser pipeline passed for Discovery through ZIP and Catalog completion, and for stale access, identity mismatch, unknown viewer state, premature END, max-pages, and packaging failure. Fresh-entry tests cover bare-list/first-range fast paths, absence-driven range exhaustion, duplicate/conflicting/nonfree states, range drift, and exact episode-row recheck. Independent Phase 04 review passed BLOCKING 0 (42 tests, 0 skipped; Ruff PASS). After the geometry correction, focused Viewer tests passed 27, 0 skipped, and the independent post-fix affected selection passed 163, 0 skipped; `ruff check src tests` passed. The full pytest run (2037 passed, 0 skipped) predates the site-only correction.

The final Tester E2E reused the previously verified isolated 296-source Discovery Catalog by SQLite backup (Discovery was not rerun during this Batch iteration), then invoked the normal standard `batch run` CLI for the 3 exact-free candidates using transparent in-process evidence wrappers. It completed 50, 40, and 32 body pages (122 total) with END, produced three ZIPs whose member order/count/CRC/hash matched the Manifests, and marked exactly those three Catalog Items completed; 293 `unknown` items stayed pending. Same-run selected-canvas RGBA pixels exactly matched every captured PNG. Independent visual review of each episode's first, middle, and last page passed with no UI/ad, blank frame, or half crop. Metrics recorded 1,189 requests and zero 403/429/5xx, challenge, CAPTCHA, or retry events; quota resources stayed unused and entitlement/grant state did not change. Reports and outputs remain isolated under `output/hanayume_experiment/tester/runs/20261010T153649Z-ac385393/` and are not committed.

The earlier AccessGuard HTTP 429 stop and one-page timeout are retained as historical failed iterations and were superseded by this complete run. The confirmed output method is rendered body-canvas PNG at the observed 828×1329 dimensions; source-native 960×1540 mapping is not broadly proven. The bounded 240×385 geometry rejects the tested MCU-8 DCT permutation path. Other works/layouts and authenticated non-consuming `今なら無料` remain unverified.

## Runtime and verification

The adapter uses the shared Crawler Chrome through the existing CDP `BrowserSession` and Playwright `Page`; it does not launch Chrome or select a profile. The AccessGuard relevant-host profile includes `hanayume.com`, `www.hanayume.com`, and the observed image host `viewer.hanayume.com`.

Implementation details, live evidence, test results, deferred authentication, and the next phase gate are recorded in the [Hanayume site note](../../../../note/10_hanayume.md) and [free-only runbook](../../../../runbooks/hanayume-free/README.md).
