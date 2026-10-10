# 花とゆめ＋ Adapter — Progress / Evidence log

Updated: 2026-10-11 (Phases 01-05 PASS / BLOCKING 0 within logged-out `無料` scope; final independent Reviewer PASS)
Branch: feat/hanayume-adapter
Implementation: **Discovery, rendered-PNG Viewer, and direct-only Batch are implemented and independently reviewed; final three-sample standard Batch-to-ZIP E2E passed in logged-out `無料` scope**
Live site Probe: **The three-sample logged-out `無料` Batch-to-ZIP E2E passed; earlier 429 and one-page timeout attempts are historical failures superseded by that complete run**
Reference seed: https://hanayume.com/episodes/8c6f15923caa0

| Phase | Status | Evidence / pending gate |
| --- | --- | --- |
| 01 Site Probe | PASS / BLOCKING 0 | 296 unique rows/range coverage, logged-out access and viewer baseline reviewed independently |
| 02 Discovery | PASS / BLOCKING 0 | strict work/range validation, complete buffering/global positions, no-login classification; independent review complete |
| 03 Viewer/Capture | PASS / BLOCKING 0 | Live Phase 05 run completed the three exact-free episodes with END and all body slots; all 122 output pages were matched against same-run selected canvas pixels |
| 04 Policy/Batch | PASS / BLOCKING 0 | 206 affected tests, 42 independent Reviewer tests, and post-fix 163 affected review tests passed; Phase 05 exercised the live direct-only Batch path for 3 candidates with no quota/grant resource use |
| 05 Independent E2E | PASS / BLOCKING 0 | Tester live E2E and final independent review passed; 3 completed Catalog items, 3 verified ZIPs, 122 pages, 9/9 sampled images visually clean; 293 unknown items stayed pending |

## User-confirmed current run scope
- User instruction: **「ログインせず、検証可能な範囲で進める」**. No login, registration, or account-gated action is in scope for this run.
- The site-local classifier distinguishes the exact raw badges `無料` and `今なら無料`. They map to `access_mode=free` and `access_mode=unknown`, respectively. Catalog persists only `access_mode`; it does not store the raw label. This work snapshot contained 3 `free` and 293 `unknown` rows; exact row scope is required.
- The three rows labeled `無料` are the current-run Batch candidates only after fresh same-work identity and exact target-row checks; a stale Catalog classification cannot override current viewer state.
- Two 「今なら無料」 samples showed an account-registration requirement and zero canvases while logged out. Preserve their Discovery rows but leave eligibility UNKNOWN/ineligible; authenticated non-consuming verification is deferred by user scope.
- Delivery expiry is not a development exclusion rule. A current-state change away from 「無料」 must fail closed at Batch entry.
- Preserve source bytes when already correct. The Viewer currently stores clean rendered body-canvas PNGs at observed dimensions; native source fidelity is not proven broadly. The measured geometry rejects only the tested MCU/DCT permutation approach.

## Initial unknowns (before the bounded follow-up probes)
1. 作品全件の終了をどのDOM/レスポンスsignalで証明できるか。話数範囲expand/もっと見るの優劣。
2. 「今なら無料」と「無料」の正確なscope、矛盾表示、会員要件、非消費なViewer entry。
3. 安定作品/話IDとサイト間重複、作品全体の話順。
4. Viewerがrenderする画像のMIME/スクランブル/タイル幾何、DCT feasibility、END/復帰挙動。
5. 同一作品で両無料状態と2〜3話のlive exampleを用意できるか。

## Phase 01 — initial live observations (2026-10-10; historical first pass, superseded by final checkpoint below)

### OBSERVED
- Confirmed the existing shared Crawler Chrome listener at the default endpoint and verified its process command line uses this repository's `.chrome-crawler` profile. The probe connected through `core.browser.BrowserSession`, opened a new Page, and closed only that Page; it did not launch or close Chrome.
- The seed `https://hanayume.com/episodes/8c6f15923caa0` returned HTTP 200 and stayed on the same path. Page title and heading identify episode 1 of the work; the episode URL path provides `8c6f15923caa0`, and the observed work link `/series/1f9f5b0d4cd52` provides a distinct work-scoped path ID.
- Episode rows are represented in the rendered DOM by `div.series-eplist-item[data-e2e="eli"]` containing `a.series-eplist-item-link`; row hrefs use `/episodes/<id>` paths. The initial rendered page contains rows whose visible labels include both exact strings `無料` and `今なら無料`; other purchase text also appears elsewhere in the page, so free classification must stay row-scoped.
- The listing exposes pagination links labeled `1-30` through `271-296`, plus `最新話から`, and a `もっと見る` button (`series-eplist-loader-btn`). The initial list is not yet proven complete and the two expansion approaches have not been compared.
- Three visible canvases were present at 828x1329 each, with 69 `img` elements elsewhere in the DOM. No page-to-canvas identity, source response, draw geometry, final-page behavior, or image provenance has been established.
- Initial probe artifacts are isolated under the ignored path `output/hanayume_experiment/`: `phase01-probe.py` and `phase01-initial.json`. The script records sanitized URL paths and DOM summaries; it does not persist response bodies or browser state.

### INFERRED
- The `/series/<id>` path is a candidate stable work identity, and `/episodes/<id>` is a candidate per-episode identity. Confirm consistency across list ranges before using either in production.
- The visible row labels are viable distinct discovery signals, but they do not yet prove that both paths grant non-consuming viewer access.

### UNKNOWN / BLOCKED
- Whether `もっと見る` reaches all 296 declared positions or what terminal signal proves completion; whether range pagination is complete and globally ordered; row identity uniqueness and position semantics.
- Whether each exact raw badge `無料` or `今なら無料` is a currently non-consuming viewer path; login, membership, expiry, and conflicting access semantics.
- Which of the canvases/images contain episode pages, their MIME/source relation, any scrambling/MCU geometry, page-order readiness, spread handling, and END/NEXT_CONTENT.
- No live Viewer-entry probe for the `今なら無料` row, list-completeness probe, or page-source probe has completed yet. Phase 01 remains open; no test result or implementation is claimed.

## Phase 01 - final evidence checkpoint (2026-10-10; independent review PASS / BLOCKING 0)

### OBSERVED

- All probes connected to the existing shared Crawler Chrome through the default CDP endpoint using `core.browser.BrowserSession`; the existing repository `.chrome-crawler` profile was verified. Each probe created and closed only its own Page. No browser launch/profile selection or normal Catalog/output write occurred.
- Seed https://hanayume.com/episodes/8c6f15923caa0 returned HTTP 200. The page URL supplies episode ID `8c6f15923caa0`; the work link observed on seed and sample pages is `/series/1f9f5b0d4cd52`. Row links are under `/episodes/<id>`.
- Listing rows are `div.series-eplist-item[data-e2e="eli"]` with a nested `a.series-eplist-item-link`; episode links use `/episodes/<id>`. Classification must stay scoped to the row: other purchase calls-to-action appear elsewhere in the page.
- The ten listed ranges are 1–30, 31–60, 61–90, 91–120, 121–150, 151–180, 181–210, 211–240, 241–270, and 271–296. One navigation per range returned counts 30×9 and 26; each had exactly one selected `a.series-sort-link.mode-current`. The 296 row IDs were all present and unique, with no duplicates. Combined order is oldest-to-newest; split labels such as 4話①/4話② show why global list positions must be retained independently of displayed episode numbering.
- The separate もっと見る experiment went 10→35→55 rows. A further click left it at 55 while the button was still visible. It has no reliable completion signal in this observation.
- Row-scoped labels on this work snapshot counted 3 無料 and 293 今なら無料; no 購入 or 待てば無料 row was observed. The three 無料 rows are episodes `8c6f15923caa0`, `9202b052ad237`, and `2ec9c6b024ee0`; all returned 200, were still labeled 無料 in their current rows, retained the same observed work link, and rendered while logged out without an entitlement action.
- The 今なら無料 samples `0e4aabaf81461` and `8160a38668d47` returned 200 and retained the same observed work path, but both displayed an account-registration requirement and had zero canvases. Registration/login was not clicked. This leaves their access unknown/ineligible under the current no-login scope.
- Viewer counters were 37, 45, and 55 for the three 無料 samples. Their first state was 1/N; midpoint native seeks reached 19/37, 23/45, and 29/55. Bounded near-end seeks reached 33/37, 41/45, and 51/55, each with a loaded/rendered 828×1329 canvas under `-cv-page-canvas`. At 35/37 in the first sample there was no visible canvas; at 37/37 the viewer added `mode-last-page` and showed terminal UI including a next-episode card. No next-episode link was clicked. This is a terminal UI observation, not proof of the exact last body page index.
- The desktop reader was in `mode-spread`. At 1/N, a `mode-empty mode-pr mode-top-pr` page and its volume-purchase link sat beside the visible body canvas. Near the end, a book-information panel with bookstore links sat beside the body canvas. Full-page and element screenshots include fixed viewer UI/overlays; they are not clean body captures. No single-page control was observed. The visible `changeVHButton` label was 縦横切替え; it was not operated.
- `#xCVPages` had 38 DOM children while the visible reader total was 37. Promo, information, good, and last UI slots are present; DOM child count is not a body-page count or terminal authority.
- Fifteen inspected viewer source responses were JPEG. Parsed SOF was baseline SOF0, grayscale single component, 960×1540, MCU 8×8. Draw traces showed 16 unique source rectangles and 16 unique destinations per source-page canvas, with repeated draw calls; exact one-to-one pairing/replay remains unproven. The observed 4×4 source tile size is 240×385: width aligns to MCU-8 and height does not (`385 % 8 == 1`). This rejects the tested MCU/DCT coefficient-permutation approach for these sources only.
- Canvas readback on episode 1 at 1/37 succeeded via `canvas.toDataURL('image/png')` as a 828×1329 PNG data URL. The data URL and pixel body were not saved. The canvas element is separate from adjacent promo/info DOM, making it a candidate clean fallback after Phase 03 verifies page identity, ordering, completeness, and pixel output.
- No 403, 429, or challenge was observed. No login, registration, paid resource, ticket, purchase, or next-episode action occurred. Visual screenshots remain only under ignored `output/hanayume_experiment/`; no source response body was saved or committed.

### INFERRED

- The `/series/<id>` and `/episodes/<id>` paths are candidate work and episode identities. Range rows were read under the seed work route; production Discovery must still validate work context and reject conflicts before yielding items.
- Range navigation is the best observed enumeration strategy. Phase 02 should fetch each declared range once, buffer the whole result, validate expected counts/current range/unique IDs and work context, assign global positions, and only then apply bounded slicing. Do not use loader growth or displayed episode numbers as completion/order authority.
- These three exact 無料 rows are currently confirmed logged-out direct-view candidates. 今なら無料 stays distinct in Discovery but is not Batch eligible in this run.
- Canvas PNG readback can isolate the rendered page pixels from neighboring site DOM, but it is not source-original and still needs Phase 03 fidelity checks.

### UNKNOWN / DEFERRED

- Authenticated, non-consuming `今なら無料` access remains unverified by user instruction and is always `unknown`/ineligible in this run.
- Phase 02 implementation validates every declared range, exact current marker/actual route, unchanged range set, same work identity, row count, unique IDs, whole-list buffering, full/incremental Catalog behavior, and global positions before yielding.
- Exact UI-counter/body-page/spread mapping remains unresolved. The observed N/N plus `mode-last-page` proves the reader's terminal UI, not a specific final body canvas. The near-end counters N−4 retain body canvases; N−2/terminal showed no body canvas in the first sample. Phase 03 must establish the last-body index and page completeness.
- Full source tile coordinate bijection, exact source-page identity binding, reconstructed pixels, and equality to the rendered canvas remain unproven. DCT is rejected only for the measured 240×385 tile geometry. If bounded source replay cannot prove exact pixels, use the canvas PNG fallback after verifying no missing/duplicate/reordered pages.
- Single-page behavior, resume/rewind persistence, other works/layout variants, and automatic next-episode transition are not verified.

### Probe artifacts, test status, and gate

- Sanitized evidence and local audit screenshots are isolated under ignored `output/hanayume_experiment/`. Main summaries: `phase01-ranges.json`, `phase01-viewers.json`, `phase01-free-samples.json`, `phase01-all-free-seeks.json`, `phase01-end-seek.json`, and `phase01-canvas-readback.json`.
- Probe commands from the repository root were `uv run python output/hanayume_experiment/probe_ranges.py`, `probe_free_samples.py`, `probe_all_free_seeks.py`, `probe_end_seek.py`, and `probe_canvas_readback.py`; Python UTF-8 output was enabled. Probe artifacts are not production tests.
- Unit, browser integration, regression, and full pytest tests were not run because Phase 01 changed no production code. No test PASS is claimed. Root's repository-wide Ruff baseline passed before production changes.
- Independent Reviewer: **Phase 01 PASS / BLOCKING 0**. The Lead authorized Phase 02; Phase 02 independent review is pending. Do not start Phase 03 until its Phase 02 review passes.
- User action needed now: none. The no-login scope is confirmed; authenticated 今なら無料 verification remains deferred.

## Phase 02 - final evidence checkpoint (2026-10-10; independent review PASS / BLOCKING 0)

### OBSERVED / IMPLEMENTED

- The adapter is registered in the Discovery registry only. It uses the existing shared CDP/Page path and existing Catalog schema. The target work header link is unique under `#xHeader`; the unique episode list is separately required under `div.series.mode-ep` because the live DOM places these structures as siblings.
- All ten live numbered routes returned HTTP 200 at the exact requested route. Each had one current range marker with the expected label, and each selected anchor linked to the exact seed episode path. Production accepts that alias only on the unique current anchor after exact actual-page URL and label checks; every nonselected numeric link remains on its numbered path.
- Full live CLI: 296 observed/new, complete `True`, stopped `exhausted`. Isolated Catalog audit: 296 unique work-scoped Sources, 296 unique global positions 1-296, 3 `free` and 293 `unknown`.
- Incremental live CLI: 5 observed/known, complete `None`, stopped `known_streak`. The adapter still fetched and validated all ten range routes and buffered all records before the first yield.
- Bounded live CLI: 3 observed/new, complete `True`, stopped `exhausted`; isolated Catalog order retained global positions `[3, 2, 1]`. All three CLI runs used only explicit files below ignored `output/hanayume_experiment/`.
- Live full command: `.venv/Scripts/python.exe -m screenshot_crawler.cli discover --key hanayume-phase02-live --mode full --watchlist output/hanayume_experiment/phase02-watchlist.yaml --catalog output/hanayume_experiment/phase02-catalog.sqlite`; incremental used the same arguments with `--mode incremental`.
- Live bounded command: `.venv/Scripts/python.exe -m screenshot_crawler.cli discover --key hanayume-phase02-bounded --mode full --watchlist output/hanayume_experiment/phase02-bounded-watchlist.yaml --catalog output/hanayume_experiment/phase02-bounded-catalog.sqlite`. Selected-route evidence is `output/hanayume_experiment/phase02-selected-ranges.json`.
- Exact single `無料` row badge maps to `access_mode=free`; exact `今なら無料`, missing/duplicate/conflicting and other badges map to `access_mode=unknown`. Catalog stores only `access_mode`; no label schema or metadata changes were made.
- A blocked-locator regression failed before the AccessGuard fix because `close()` remained pending, then passed after `_visible_captcha_provider` began re-raising `asyncio.CancelledError`. No stop classification or host rules changed.

### TESTS / GATE

- Focused combined Hanayume Discovery, AccessGuard, CLI registration, and local browser integration selection: 46 passed, 0 skipped. Full `ruff check src tests`: passed.
- Phase 02 independent Reviewer: **PASS / BLOCKING 0** (final review confirmed 46 tests passed, 0 skipped; Catalog audit and documentation corrections accepted). Lead authorized Phase 03-A bounded probe only. No Phase 03 production contract is approved yet.
- Authenticated non-consuming `今なら無料` behavior remains intentionally unverified under the user-confirmed no-login scope. Viewer/capture, Batch, and standard E2E phases have not started.

## Phase 03-A - bounded live probe (complete; 2026-10-10; no production changes)

- Lead authorized evidence gathering only. The probe used the shared CDP browser and existing viewer controls; no login, registration, purchase, entitlement, ticket, quota, DRM bypass, or next-episode action occurred. No 403/429/challenge was observed.
- Fresh preflight on each of the three confirmed `無料` rows (`8c6f15923caa0`, `9202b052ad237`, `2ec9c6b024ee0`) found the unique target row in the same work listing, with the exact current label. The third target was reached by following its observed `/series/1f9f5b0d4cd52/1` range link labeled `1-30`; the selected range and same-work/episode links were checked before opening the exact episode URL. The episode pages retained the scoped work path `/series/1f9f5b0d4cd52`.
- Viewer counters were 37, 45, and 55. `#xCVPages` contained 38, 46, and 56 slots respectively. In each observed sample, slot 0 was top promotion; slots 1 through N−5 (32, 40, and 50 slots) were **structural body candidates**, not proof that every slot already had a rendered canvas. Many were placeholders with no canvas; only current/preloaded viewport spreads had loaded canvases. Slot N−4 was `mode-ci`, slots N−3/N−2 were promotional empty slots, slot N−1 was `mode-good`, and slot N was `mode-last`. At counters N−4 (33/37, 41/45, 51/55), the final body canvas at slot N−5 was present; terminal N/N showed only terminal/promotion UI and no body canvas. This supports the observed sample mapping but does not establish a site-wide rule. The three viewers were in `mode-spread`; no single-page control was established. Terminal UI is not by itself body-completeness proof.
- A clean 828×1329 body canvas readback succeeded and excludes adjacent promotion/info DOM. This is the observed backing size for the selected canvas, not a fixed contract for all supported reader layouts. On the first sample's initial body page, the JPEG source at `viewer.hanayume.com` was rendered through one 960×1540 scratch-canvas generation using 16 source/destination tile rectangles with full coverage. The same retained image elements replayed to that scratch size and through the observed 828×1329 final scale produced exact pixel equality with the scratch and visible body canvas. This is a positive one-page source-derived pixel proof, not proof for every page or source response byte preservation. On the third sample, the observed tile target and final visible draw used different canvas IDs; their exact relationship is unresolved. The bounded evidence does not justify generalizing source-native reconstruction to every page.
- Observed source responses were HTTP 200 `image/jpeg` from `viewer.hanayume.com`. The previously measured 240×385 tiles remain incompatible with the tested MCU-8 DCT permutation path; no further DCT exploration was done. The host is a candidate for a narrowly scoped relevant-host AccessGuard profile if production capture relies on it; that change needs its own evidence-backed Phase 03-B contract.
- Recommended bounded Phase 03-B decision for Lead: use source-derived pixels only on a page whose active target, source identity, completed generation, complete tile coverage, exact full-source rectangle, final scaling and replay equality are proven; capture any mutable scratch pixels at the proven draw event, before reuse, and encode later. Require the invariant per page. When that proof is absent, use the clean body-canvas PNG and fail closed on readback failure; never silently substitute a viewer screenshot. The captured 3-sample wrapper/body candidate mapping may guide the page-state gate, but current-page readiness, full page order, every spread side, and END must be verified during implementation before production claims.
- Probe script and sanitized summary: `output/hanayume_experiment/phase03a_probe.py` and `output/hanayume_experiment/phase03a-viewer-binding.json` (ignored). Command from repository root: `$env:PYTHONUTF8='1'; $env:PYTHONIOENCODING='utf-8'; .venv/Scripts/python.exe output/hanayume_experiment/phase03a_probe.py`. The evidence stores metadata only; it contains no page bodies, image bodies, signed query strings, or screenshots. It is a probe artifact, not a production test.
- No tests were run because this checkpoint contains only bounded probes and documentation. No Phase 03 production code or test contract has been approved. Independent Phase 03-A review and Lead adjudication are pending; do not start Phase 03-B implementation before that gate.

### Remaining Phase 03 questions

- The one-page replay proof does not establish exact source-to-body binding for every first/middle/final body page; the third sample included distinct tile-target and visible-canvas IDs. A per-page proof or safe clean-canvas fallback remains necessary. Structural slots 1 through N−5 are only candidate wrappers; placeholders without the exact loaded/rendered canvas are not CONTENT.
- The observed N−5 candidate-wrapper relation is limited to these three episodes and desktop spread mode; runtime capture must require the current wrapper's actual loaded/rendered canvas and use that selected canvas's dimensions rather than assuming 828×1329 globally. Other layout variants, single-page mode, resume/reopen behavior, page-change readiness races, and automatic NEXT_CONTENT are not established.
- Authenticated non-consuming `今なら無料` access remains intentionally unverified under the no-login instruction.

## Phase 03-B ? Viewer / rendered PNG implementation checkpoint (2026-10-10; local review PASS / live gate pending)

### IMPLEMENTED / OBSERVED

- Added a site-local manual Viewer adapter and registered it in the manual crawl registry. Discovery remains in its own registry. Batch registration and direct-only policy were added in the separately authorized Phase 04 checkpoint below. No Core change was added for Viewer capture.
- Phase 03 originally used a full range preflight; Lead-approved Phase 04 freshness refinement supersedes that entry scan. Current Viewer/Batch entry checks the exact bare same-work URL and finite range set, stops on a unique exact `無料` target row in the bare listing or first observed numbered range containing it, rejects duplicate/conflicting/nonfree rows immediately, and exhausts ranges only when target is absent. It then rechecks exact work and target row on the episode page. Discovery still validates all ranges and full-work uniqueness.
- Viewer parser accepts only the observed desktop spread structure. Candidate body wrappers do not become content until the expected active canvas is marked loaded and rendered, belongs to its `.-cv-page-canvas` wrapper, has positive observed dimensions, and is fully visible. Two exact offscreen loading states were observed during bounded diagnostics: `mode-loading mode-req-render` and `mode-loading`, both with no canvas. These remain non-ready placeholders; an unobserved partial marker/class remains UNKNOWN.
- The adapter rewinds using the observed public seek control and advances by one verified spread step. It requires three stable metadata observations for counter/active/ready slots, captures each spread side atomically as a canvas PNG, validates PNG decoding and exact selected-canvas dimensions, rejects gaps/duplicates, and reaches terminal UI only after every body slot is captured. It never follows the next-episode card.
- `get_capture_target()` and `get_capture_targets()` now reject generic fallback. A local Runner-level browser test injects a direct PNG timeout and proves `capture_locator` is not reached. This closes the Core's normal timeout-to-locator fallback path without changing Core.
- Image strategy is rendered body-canvas PNG. It retains exactly the selected canvas pixels at its actual dimensions, but not the original 960×1540 source resolution. A bounded source replay proof covered one page only; the tested 240×385 geometry rejects the measured MCU-8 DCT permutation route. No UI screenshot is used as output.
- Added the observed `viewer.hanayume.com` image host to the narrow relevant-host set. Existing profile behavior remains stop-on-relevant 403/429/challenge.
- At this historical Phase 03 checkpoint, updated site README and `note/10_hanayume.md` to Discovery + manual Viewer scope, exact raw labels, capture behavior, fidelity limit, and no-login deferral. Phase 04 later added Batch registration and its direct-only policy; see the current Phase 04 checkpoint below.

### TESTS / LIVE GATE / REVIEW

- Focused adapter tests: `tests/unit/test_hanayume_adapter.py tests/integration/test_hanayume_adapter_browser.py` — **14 passed, 0 skipped**, 5 pytest-asyncio deprecation warnings. Expanded affected selection including Hanayume Discovery unit/browser tests and CLI registration: `.venv/Scripts/python.exe -m pytest -q tests/unit/test_hanayume_adapter.py tests/integration/test_hanayume_adapter_browser.py tests/unit/test_hanayume_discovery.py tests/integration/test_hanayume_discovery_browser.py tests/unit/test_cli.py` — **135 passed, 0 skipped**, 288 pytest-asyncio deprecation warnings. `.venv/Scripts/python.exe -m ruff check src tests` — passed.
- First live Runner attempt failed closed at first-page initialization on an unrecognized offscreen `mode-loading mode-req-render` placeholder and captured zero pages. A single bounded fresh-free diagnostic observed that exact pair plus `mode-loading` alone, both without canvas; fixture coverage was added before broadening the accepted state. A later live attempt was stopped by shared AccessGuard on an HTTP 429 from Hanayume with `Retry-After: 1`. No retry, login, registration, unlock, purchase, or further episode navigation occurred.
- The required live three-sample check and first/middle/final pixel evidence are NOT VERIFIED. Phase 03 local independent review passed BLOCKING 0; do not claim overall Phase 03 live acceptance. Phase 04 local integration was separately authorized while the live gate remains open. Phase 05 live verification remains pending explicit Lead authorization.
- Do not perform further live navigation until the Lead explicitly authorizes a fresh bounded attempt. Stop immediately on a new 403/429/challenge; do not exclude the relevant host, weaken AccessGuard, or add retry logic.
- Isolated research files live under ignored `output/hanayume_experiment/phase03b_*`; the first Runner failure diagnostic may contain local screenshot/page HTML, all ignored and uncommitted. The later metadata-only diagnostic records sanitized wrapper classes/canvas readiness. No image or page body was committed.
- Independent Reviewer reported one blocking risk in the first review pass: Core's normal capture timeout can fall back to locators/screenshots. The site-local generic capture hooks now reject that path, and the Runner-level regression covers it. Final Phase 03 local review: PASS / BLOCKING 0; live remains NOT VERIFIED.

### Remaining limitations

- The initial HTTP 429 stop and one-page timeout described below are historical failed iterations; the later Phase 05 run completed all three exact-free candidates and supersedes those failures. No retry policy or AccessGuard weakening was introduced.
- Authenticated, non-consuming `今なら無料` access remains unverified by user instruction. Those rows remain `unknown`/ineligible for Batch in this run.
- Source-native fidelity is not established broadly. Current output is clean rendered body-canvas PNG at the observed 828×1329 dimensions, reduced from the 960×1540 source canvas. Other works, viewer modes, resume/layout variants, and source-generation mappings remain unverified.


## Phase 04 - direct-only Batch integration (2026-10-11; local independent review PASS / BLOCKING 0)

### IMPLEMENTED

- Registered `HanayumeSitePolicy` and `HanayumeAdapter` with the existing Batch policy/adapter registries. The policy permits only available sources with exact `access_mode=free` and `direct`; it rejects unknown, quota, paid, owned, grant, rental, and unavailable. It declares no access resources or grant-only passes. The adapter accepts the standard direct strategy as its already-observed free path; no Core or Catalog schema change was made.
- Batch entry checks the exact bare same-work URL and finite declared ranges. It stops at a unique exact target row in that listing, otherwise follows only declared numbered routes and stops at the first target after exact selected-range/route, unchanged-range-set, complete page count, and page-local ID checks. Duplicate/conflicting/nonfree target states fail immediately; all routes are exhausted only if the target is absent. The exact episode is reopened and its scoped work and row label are checked again. Re-entry requires one canonical first-party episode href with no query/fragment and the exact target ID; foreign-origin and query-suffix target-like rows fail closed.
- Discovery remains whole-work authoritative: all declared ranges, count/identity coverage, and global display positions are fully validated before its records are yielded. The optimized preflight is a freshness check only.
- A synthetic browser pipeline completed Discovery -> Catalog -> Planner -> Executor -> Runner -> Manifest/ZIP -> Catalog completed on the isolated test Catalog/output. It verified native global position in the archive prefix and that a completed item is skipped on replanning. Failure fixtures cover stale free-to-`今なら無料`, wrong work, unknown slot, premature END, max-pages, and package failure; failed runs remain pending without a ZIP Artifact. Entitlement/quota state remains unchanged.

### TESTS / LIVE / REVIEW GATE

- The final Phase 04 affected selection passed: `.venv/Scripts/python.exe -m pytest -q tests/unit/test_batch.py tests/unit/test_access_guard.py tests/unit/test_hanayume_policy.py tests/unit/test_hanayume_adapter.py tests/unit/test_hanayume_discovery.py tests/integration/test_hanayume_adapter_browser.py tests/integration/test_hanayume_discovery_browser.py tests/unit/test_cli.py` -> **206 passed, 0 skipped**, 324 pytest-asyncio deprecation warnings. `.venv/Scripts/python.exe -m ruff check src tests` passed; `git diff --check` passed with only existing CRLF normalization warnings. No live Batch artifact was produced in the later third-sample run; the Viewer captured one slot before the next-spread timeout.
- Independent Phase 04 Reviewer: PASS / BLOCKING 0 (42 tests, 0 skipped; Ruff PASS). Lead-owned full `pytest -q` completed before the latest site-only geometry fix: **2037 passed, 0 skipped, 3737 warnings in 435.81s**; log `output/hanayume_experiment/final-full-pytest.log`. Latest site-only focused tests after the fix: 27 passed, 0 skipped. The subsequent independent geometry review passed BLOCKING 0 with 163 affected tests, 0 skipped, and Ruff PASS. Final live evidence is recorded in the Phase 05 checkpoint below.

## Phase 03-C / Phase 05 initial live failure follow-up (2026-10-11; superseded by final PASS below)

- The latest authorized Tester Batch attempt used the third confirmed `無料` target, `2ec9c6b024ee0`. Fresh same-work exact-free preflight passed, the viewer rewound to 1/55, and the Runner saved body slot 1. At 3/55 it timed out waiting for the next spread. No ZIP Artifact was created and the Catalog Item remains pending. This is a failed live iteration, not partial completion or a Phase 03/05 PASS.
- One bounded metadata-only follow-up reached and held counter 3/55. The viewport was 1906×986. Snapshot metadata reported active wrappers `[1, 2, 3]` and ready canvases `[2, 3]`. Wrapper 1's bounds began 15.33 px inside the viewport; its 828×1329 canvas was entirely offscreen. Canvases 2 and 3 were the visible spread. No 403/429/challenge was observed during this follow-up.
- Cause: snapshot logic considered any wrapper/viewport intersection active, so a 15.33 px sliver from the previous offscreen wrapper was included as an active page. The evidence-backed site-local correction defines active wrappers by their center being inside the viewport. Selected canvas visibility remains full-viewport; exact expected slot set, loaded/rendered state, atomic readback, order and END checks are unchanged. A currently active loading spread side remains blocking.
- Regression coverage includes a clipped prior wrapper that must be excluded and an active loading side that must still produce LOADING rather than a capture. Post-fix command: `.venv/Scripts/python.exe -m pytest -q tests/unit/test_hanayume_adapter.py tests/integration/test_hanayume_adapter_browser.py` -> **27 passed, 0 skipped**, 14 pytest-asyncio deprecation warnings. Scoped Ruff command: `.venv/Scripts/python.exe -m ruff check src/screenshot_crawler/site_adapters/hanayume tests/unit/test_hanayume_adapter.py tests/integration/test_hanayume_adapter_browser.py` -> passed. `git diff --check` passed with Git's LF/CRLF normalization warnings only.
- Probe evidence is isolated at `output/hanayume_experiment/phase03c-advance-metadata.py` and `output/hanayume_experiment/phase03c-advance-metadata.json`; command: `.venv/Scripts/python.exe output/hanayume_experiment/phase03c-advance-metadata.py`. The sanitized record contains wrapper/canvas geometry and state metadata only, no image bytes, source URL, or page body.
- Independent geometry-correction review: **PASS / BLOCKING 0**. The Reviewer ran the post-fix affected selection: **163 passed, 0 skipped, 297 known warnings**; `ruff check src tests` and `git diff --check` passed. The earlier full-suite result (2037 passed, 0 skipped) predates this site-only fix; the independent post-fix affected review was accepted as the final local regression gate without another full rerun. The later successful Phase 05 live run supersedes the one-page timeout recorded in this section.

## Phase 05 - final live standard Batch / ZIP E2E (2026-10-11; Tester PASS)

- Isolated harness command: `.venv/Scripts/python.exe output/hanayume_experiment/tester/hanayume_e2e.py --live --reuse-catalog output/hanayume_experiment/tester/runs/20261010T152230Z-2794388b/catalog.sqlite`. It reused the previously audited 296-row Discovery Catalog by coherent SQLite backup; it deliberately did not rerun Discovery. The harness called the standard CLI `batch run --site hanayume --catalog <isolated-catalog> --output-root <isolated-batch> --library-dir <isolated-library> --limit 3` with transparent in-process audit wrappers to retain manifest/progress evidence before the normal packager removed its temporary run directory. Production adapter/Core behavior was not changed by the harness.
- Baseline was 296 sources with no count drift: `free=3`, `unknown=293`. Selected episodes were `8c6f15923caa0`, `9202b052ad237`, and `2ec9c6b024ee0`. The three runs succeeded with `stop_reason=end` and body totals 32, 40, and 50 (122 total), with zero body-count drift. For every page, an independent canvas read occurred in the same run before advancing; decoded RGBA pixels exactly matched the adapter PNG. Fingerprints were traced through Manifest and ZIP members.
- Three ZIP Artifacts were created. The Tester verified member order/count and CRC/hash integrity against each Manifest. Independent visual review sampled first/middle/last body pages for all three episodes (9 images): all were clean comic body canvases, without viewer chrome, ad/promotion, blank frames, or half-page crops. All three selected Catalog Items became completed; the remaining 293 `unknown` Items stayed pending. The previous failed run record was retained. Quota resource count remained zero and entitlement/grant state was unchanged.
- Live metrics: 1,189 requests; 0 HTTP 403, 429, or 5xx; 0 challenges, CAPTCHAs, or retries. No login, registration, purchase, ticket, or quota action occurred. Authenticated non-consuming `今なら無料` access remains unverified and unsupported in this run.
- Image method: clean rendered body-canvas PNG at observed 828×1329, preserving the visible canvas pixel content without UI. This is lower resolution than the 960×1540 source. The one-page source-replay proof does not generalize; 240×385 tile height 385 is unaligned to 8×8 MCU geometry, so the tested MCU-8 JPEG DCT permutation is rejected. Other source-native mapping variants remain future research, not a current claim.
- Final Tester report: `output/hanayume_experiment/tester/runs/20261010T153649Z-ac385393/final_report.json`; independent assessment: `output/hanayume_experiment/tester/runs/20261010T153649Z-ac385393/tester_assessment.json`; sampled visual evidence remains under the same ignored run directory. The harness, reports, Catalog, ZIPs, and screenshots are isolated under `output/hanayume_experiment/` and are not committed.
- Test gates: pre-fix full `pytest -q` **2037 passed, 0 skipped, 3737 warnings**; after the geometry fix, focused implementation selection **27 passed, 0 skipped**, independent post-fix affected selection **163 passed, 0 skipped, 297 known warnings**, `ruff check src tests` PASS, and `git diff --check` PASS. No full-suite rerun was requested after the site-only change because Core was unchanged and the post-fix independent affected selection passed.
- Final outcome: **Phases 01-05 PASS / BLOCKING 0** for the user-authorized logged-out `無料` scope. Final independent Reviewer: PASS / BLOCKING 0 (42 fresh tests, 0 skipped; Ruff, diff, and independent SQLite/three-ZIP/122-PNG artifact audits passed). The only outstanding access classification is authenticated `今なら無料`, which remains Discovery `unknown`, Batch-ineligible, and NOT VERIFIED under the no-login instruction.

## Checkpoint template (append after each phase)
### Phase XX — YYYY-MM-DD / commit
- Scope & diff:
- OBSERVED facts (URLs stripped of signed query; no copyrighted body):
- INFERRED hypotheses:
- UNKNOWN/BLOCKED:
- Unit / browser integration / live / selected regression (pass, fail, skips):
- Reviewer BLOCKING / NON-BLOCKING / VERIFIED:
- Tester PASS / FAIL / NOT VERIFIED:
- Capture fidelity/provenance and fallback:
- User decisions needed (at most 3) / next action:

Do not mark a phase PASS without its required observations/tests/reviewer gate.

