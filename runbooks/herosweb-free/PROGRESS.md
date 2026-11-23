# HERO'S WEB Free-only Site Adapter — Progress

Date initialized: 2026-11-22
Status: **Phases 01–06 PASS / BLOCKING 0. A10 passed full A native capture (10/10 VP8L pages, END, ZIP/Catalog audit); B14 passed full B native capture (38/38 VP8L pages at 844x1200, END, ZIP/Catalog audit). Original JPEG bytes/recovery remain unproven and are a separate follow-up.**
Site key: `herosweb`.
Implementation branch: `feat/herosweb-free`, based on `main` at `ec0afc3`; do not auto-merge.
Authority: [README.md](README.md), subordinate to `AGENTS.md` and repository design documents.

## Confirmed user requirements

- Build the complete Discovery → Catalog → Batch → Manifest/ZIP path, using Hanayume and Younganimal as structural references without assuming their site-specific semantics transfer.
- The first supported execution path is direct/free only. Discovery recognizes `quota` and `paid`, but ticket, wait, coin, purchase, login, and rights actions are out of scope. Ambiguous rows remain `unknown`.
- User-confirmed labels: `無料` and `今なら無料` mean free when the current page proves access; a coin icon with a positive variable price means paid; `待つと無料` / `すぐ無料` are quota labels.
- Capture fidelity order: verified original bytes (or rigorously lossless restoration) → verified source-native lossless WebP → rendered canvas PNG → body screenshot PNG.
- `/seriesh/` is unsupported. The user separately reported `/series/fdf345d17d2b6`; it was not added as a tested seed.

## Current evidence summary

| Area | Status | Evidence and limits |
| --- | --- | --- |
| Discovery and access classification | PASS | Two supplied Works; 108 unique sources, 84 free / 20 quota / 4 paid / 0 unknown. Full and Incremental preserved IDs, positions and digests. |
| Free Viewer and Batch | PASS | A10: 10 native VP8L pages; B14: 38 native VP8L pages. Both reached actual END and passed independent ZIP/Catalog audits. Phase 05's earlier rendered-PNG audit remains preserved at `output/herosweb_experiment/phase05-independent/proofs/20261123/phase05-final-independent-audit.json`. |
| Source-native pixel implementation | PASS for A10 and B14 observed profiles | A10 independently verified 10/10 VP8L pages at 1440x2048; B14 independently verified 38/38 VP8L pages at 844x1200, with exact source-PNG RGBA, tile history, replay and stability proofs. Original JPEG bytes remain unproven. |
| Original JPEG bytes/restoration | UNPROVEN / NOT IMPLEMENTED | The bounded diagnostic associated natural JPEG bytes to the exact first-body source, but the reconstruction helper accepted no candidate. Do not infer original fidelity from dimensions or visual similarity. |
| Post-implementation live verification | A10 A / B14 B PASS | A10 and B14 reached actual END and produced independently audited ZIP Artifacts 4 and 6. Item 21 and Item 103 are completed. B10 remains a historical rendered-PNG run. |

## Phase gate

| Phase | State | Evidence |
| --- | --- | --- |
| [01 Site Probe](01-site-probe/README.md) | PASS (supported scope) | Work/range identity, free/quota/paid markers, viewer roles and actual END observed. |
| [02 Discovery](02-discovery/README.md) | PASS, including reopened B3 redirect review | Guarded Full/Incremental audit with stable 108-row inventory. |
| [03 Viewer/Capture](03-viewer-capture/README.md) | PASS for A/B observed native profiles | A10 verified 10 native VP8L pages at 1440x2048; B14 verified all 38 native VP8L pages at 844x1200 with exact source pixels and actual END. |
| [04 Free Batch](04-free-batch/README.md) | PASS / BLOCKING 0 | Direct-only policy, CLI wiring, synthetic retry/no-END tests and isolated standard CLI sample. |
| [05 Independent E2E](05-e2e/README.md) | PASS / BLOCKING 0 | Tester A/B standard CLI, Catalog and artifact audit; two earlier HTTP 429 failures are retained as history. |
| Phase 06 Source-native | PASS / BLOCKING 0 | A10 and B14 full-run independent audits passed, including exact VP8L decoded RGBA, complete capture order, actual END and ZIP/Catalog proof. Original-byte recovery is not part of Phase 06 and remains unproven. |

## B14 final full B native checkpoint - 2026-11-23

B14 is the final standard-CLI full B run. Independent audit passed all 38 ZIP members at 844x1200: every VP8L WebP decoded to the exact retained source-PNG RGBA, and each page had complete 16-tile history, exact replay, stable target pixels and current free identity proof. Manifest/ZIP order, CRC and pre-package manifest/progress digests matched. After all 38 bodies were captured, terminal END was confirmed at public seek 1 with Last wrapper index 44. The contact sheet was visually checked for upright page content without UI.

- Audit: `output/herosweb_experiment/native-independent/live-20261123-03/proofs/B14-full-independent-audit.json`.
- Run 19 succeeded at END with 38 pages; Artifact 6 is the 17,021,762-byte ZIP with SHA-256 `70b6c574e7cce30654ee2cb22e1da44fdb071848d1e63abad396c6cc2b084d95`. Item 103 is completed. All 108 Source rows and the resource rows are unchanged; prior Run/Artifact history is preserved. The final replan has 0 eligible/direct/quota candidates and skips the completed item.
- Metrics recorded 719 HTTP 200 responses, with no observed 403/429/5xx, challenge, CAPTCHA or retry. The shared source/config freeze was unchanged (230 Python files plus runtime configuration). Final reviewed SHA-256: adapter `e2bb2c3a8902fc54140fd9ae7ce55fc0663aecf8b7e32d4a6d779ba8d011b6b7`; native helper `0506590653274ab030cf583d778d45c7870ee697adf9a9d4dd2b68d109586787`; adapter browser test `3d019e884e2e48af87259cc544a1ec4550e1f714f048fbfcf3922ad67e9f3576`; native unit test `869c13adac88a4c76119052525ad693a52395a52c54dd1f7497af9d44740c758`.
- The diagnostic recorder emitted stale 1440-only profile warnings. The independent audit used the retained per-page proof and confirmed all 38 B pages passed the 844x1200 profile; those warnings did not indicate PNG fallback. Original JPEG bytes remain unproven, not impossible.
- A10 remains the full A native pass: 10/10 VP8L pages at 1440x2048, END and ZIP/Catalog audit. B10 and B11/B12/B13 remain historical checkpoints superseded by B14 for current full-run status; their individual probe limits are retained below.

## User-authorized local integration checkpoint - 2026-11-23

The user explicitly authorized committing the current HERO'S WEB version and
merging it into local `main`; no push was requested. The implementation commit
is `4f9550a`; integration merge commit `7335e5e365671fc9c9e3a274fc381cecff82fba7`
includes main base `f76e723` and was fast-forwarded successfully to local `main`.
The feature branch remains available. No push was performed. The current shared Batch contract permits one fresh-Page retry
for an eligible acquisition timeout, with existing inter-candidate pacing and
a maximum of two attempts total. HERO'S WEB does not override that behavior;
AccessGuard stops, unknown state, same-content/max-pages and capture/native-proof
failures remain non-retryable.

- Targeted generic retry command: `.venv\Scripts\python.exe -X utf8 -m pytest tests/unit/test_batch_executor.py -k retry --basetemp "$env:TEMP\hweb-main-merge-retry" -q --tb=short` — exit 0, 25 passed, 133 deselected, 226 existing asyncio warnings, 13.60 s.
- Combined pre-merge suite covered the three HERO unit files, two HERO browser files, CLI/runtime settings, and registration resolver/draft/service. Log: `output/herosweb_merge/merged-tests.log`. Result: exit 0, 597 passed, 1 skipped, 594 existing asyncio deprecation warnings, 331.55 s. The sole skip is `tests/unit/test_registration_draft.py:165`, optional `pytest.importorskip('pykakasi')`.
- Changed-HERO Ruff and cached `git diff --check` passed. Final independent review: PASS / BLOCKING 0. The main-user-changes preservation audit passed at `output/herosweb_merge/main-user-changes-preservation.json`: protected `.gitignore`, BookWalker note/README/adapter/test and Watchlist hashes are unchanged; the original `crawler.yaml` content and values are preserved, with only the approved HERO block added. Protected user files remained unstaged and outside the merge commit. No post-merge live verification has been performed; the A10/B14 live proofs above predate local-main integration.

## A10 / B10 historical full-run checkpoint - superseded by B14

The approved source/config freeze was unchanged for both full runs (230 Python files plus runtime config). A10 passed independent full-capture audit: all 10 pages were lossless VP8L WebP at 1440x2048; decoded RGBA matched each source PNG; draw history, replay and stability proof was complete; RTL order was 1, 2-3, ... 10; and actual END was confirmed at seek 1 / Last. Pre-package manifest/progress hashes, ZIP CRCs and Catalog Artifact/Item state matched. B10 completed 38 pages as rendered canvas PNG at 934x1329, reached actual END and passed ZIP/Catalog audit. B13 later established a bounded B-native source-history profile, but did not run a full B native capture.

- A10 audit: output/herosweb_experiment/native-independent/live-20261123-02/proofs/A10-full-A-independent-audit.json.
- B10 audit: output/herosweb_experiment/native-independent/live-20261123-02/proofs/B10-full-B-independent-audit.json.
- Combined Catalog/plan/freeze audit: output/herosweb_experiment/native-independent/live-20261123-02/proofs/A10-B10-final-catalog-freeze-plan-audit.json.
- At the B10 checkpoint, native eligibility was UNKNOWN: the draw logger was not installed, records for slots 1-7 were evicted, and slots 8-38 reported source_candidate_unavailable. B14 later independently verified native output for all 38 pages; retain B10's observation only as historical context.
- Runs 14 (A10) and 15 (B10) succeeded, producing Artifact 4 (A native VP8L) and Artifact 5 (B rendered PNG). Runs 1-13 and Artifacts 1-3 remain preserved. Items 21 and 103 changed from pending to completed. The other 108 source/resource rows are unchanged. The selected replan has 0 direct and 0 quota candidates, 106 disabled sources and 2 completed items.
- A10 native acceptance is PASS for its observed profile. B10's rendered capture, END and ZIP/Catalog passed, but its own native result was not recorded; B14 later superseded that limitation. Original JPEG recovery remains unproven.
- Source verification: affected suite 81 passed, 0 skipped, 5 existing asyncio warnings; final targeted resumed-hydration tests 4 passed, 0 skipped. Changed-path Ruff, py_compile and git diff --check passed. Frozen hashes: adapter 297549a18a35490939b8b97982789bd3133cccc1aad58fcde3a32cc8ecd52230; native helper 39aa583e8800d3ff0a1016c37c3215454226e79f080021c6793ba44fccbd890a; browser tests 2933cd250a01a7c71d46f305c9ec4fc8e186e0905fe823085510b0c308d28a5a; native unit tests ecd3dc24137484936df4bb9200f4edeb4e6331fded9212d3159083e41f8758b6.
## B11 bounded diagnostic - historical, superseded by B13/B14

B11 used a new isolated live-03 clone and stopped after the expected max_pages=3 diagnostic. It saved three rendered PNGs, did not reach END, produced no ZIP or new Artifact, and did not run B beyond those three pages. Twelve viewer draw events were observed. On the first body, the immediate draw source was an HTMLCanvasElement sized 844x1200 and the target was 934x1329, with drawImage arguments [0,0,844,1200,0,0,934.5,1329]. The observed source/target contexts were sRGB/unorm8, identity transform, alpha 1 and source-over compositing. At the B11 checkpoint the upstream candidate was unavailable and B's tile mapping was not yet known. B13 later established the exact source-grid profile and B14 verified full B native output; B11 remains a bounded historical diagnostic only.

- Audit: output/herosweb_experiment/native-independent/live-20261123-03/proofs/B11-first3-diagnostic-audit.json.
- Raw diagnostic metadata: output/herosweb_experiment/native-independent/proofs/live20261123B11first3/.
- Upstream drawing history was not logged. The source canvas size is an observed canvas dimension, not a wire-format, tile-size or complete-source claim. Do not infer JPEG dimensions, 211x300 tiles, or a reason later pages lacked candidates. A legacy A07 draw-time predicate being false is diagnostic metadata only and does not prove current logical acquisition rejected slots 2/3.
- The clone's source/resource/identity/config rows remain unchanged (108 sources); Run 16 was diagnostic only, existing five Artifacts were preserved, and no new Artifact was added. The public reset left Item 103 pending in that clone. B14 later independently audited Run 19 and Artifact 6 for full B native capture. Original JPEG bytes remain unproven.
## B12 resumed-loading profile extension - historical, superseded by B14

The B12 parse audit observed a second exact hydration signature on the 45-wrapper / 38-body profile. At seek range 1-45, step 2, value 41, only mode-has-pr was missing. The current pair (wrapper indices 4-5) and next wrapper 6 were loading/req-render with no canvases; the following observation had the real PR flag. No other required root mode was missing. The exact audit paths are:

- Parse snapshots: output/herosweb_experiment/native-independent/proofs/live20261123B12first3/herosweb-0f023839d7bca/parse-layout-audit.json.
- B12 diagnostic summary: output/herosweb_experiment/native-independent/live-20261123-03/proofs/B12-live-first3-audit.json.

The site-local initialization wait now accepts only the two recorded resumed profiles: (wrapper count 17, body count 10, seek max 17, value 13) or (45, 38, 45, 41). Both still require exact current document identity, exactly the PR mode missing, strict validation of a shallow provisional snapshot, loading wrappers 4-6 with no canvases, and the real PR mode before layout freeze and rewind. The wait remains bounded and rechecks URL, header and access guards. This change does not affect draw-time mode rules, native-source dimensions, materialization, or capture.

- Targeted browser command: .venv\Scripts\python.exe -m pytest tests/integration/test_herosweb_adapter_browser.py -k "resumed_pr_hydration_waits_then_rewinds_to_native_first_spread or resumed_missing_pr_mode_times_out_without_capture or resumed_pr_wait_rejects_a_second_missing_required_mode" --basetemp "$env:TEMP\hweb-b12-initial" -q --tb=short. Result: exit 0, 7 passed, 56 deselected, 5 existing asyncio warnings, 35.01 s.
- The delayed-real-PR success/rewind, permanent-missing timeout, and second-required-mode rejection each cover the B profile; the A profile and episode-ID-neutral case remain covered.
- Independent source review: PASS / BLOCKING 0. Only adapter.py and the existing Hero adapter browser test were changed; native capture/helper, configuration and shared code were untouched. Final hashes: adapter CD543CF79283D3A65E8CBE2D7C1780A322515CFAAF31DEC1BE3974B8127A89F4; browser test 8707BDB814431BC72818DAA10F87A3F4AC8FADA44856AEFB05631D8E9D09EA9.
- Ruff check on both changed Python files, py_compile and git diff --check passed at that B12 checkpoint. This was synthetic regression coverage, not a live capture; B13 and B14 later established the B native profile and full-run result.

## B13 observed source-grid profile and synthetic implementation - historical, superseded by B14

B13 is a bounded max-pages-3 diagnostic, not a full capture: it stopped before END, ZIP and Artifact creation. The audit observed slots 2/3 at public seek 43 on Work B. Each selected 844x1200 source canvas had 16 upstream `HTMLImageElement` draws with an exact 4x4 grid of 211x300 integer source/destination rectangles. The source canvas was reused between slots, and the immutable draw-time snapshots and exact decoded RGBA comparison are covered by the synthetic spread test. Context evidence was sRGB/unorm8, identity transform, alpha 1 and source-over. No JPEG/wire-format/original-byte claim follows from this canvas evidence.

- B13 audit: `output/herosweb_experiment/native-independent/live-20261123-03/proofs/B13-live-first3-audit.json`.
- Raw draw-history evidence: `output/herosweb_experiment/native-independent/proofs/live20261123B13first3/herosweb-0f023839d7bca/capture-signature-audit.json`.
- The supported native source profiles are now exact and bounded: A 1440x2048 with 16 `HTMLImageElement` tiles of 360x512, and B 844x1200 with 16 `HTMLImageElement` tiles of 211x300. Both require an exact integer 1:1 4x4 bijection and full source replay/decoded RGBA proof. Only A claims 8-pixel alignment; B does not claim MCU alignment.
- This code change is local to the HERO'S WEB native capture validator, adapter materializer and existing focused unit/browser tests. B10 was the latest full B run at this checkpoint; B14 later completed and passed full B native audit. Original JPEG bytes remain unproven.
- Targeted command: `.venv\Scripts\python.exe -m pytest tests/unit/test_herosweb_native_capture.py tests/integration/test_herosweb_adapter_browser.py::test_herosweb_native_source_spread_is_lossless_and_draw_classes_can_hydrate_later tests/integration/test_herosweb_adapter_browser.py::test_herosweb_native_844_profile_preserves_reused_canvas_spread --basetemp "$env:TEMP\hweb-profile-final" -q --tb=short` — exit 0, 34 passed, 0 skipped, 5 existing pytest-asyncio deprecation warnings, 22.32 s.
- Affected command: `.venv\Scripts\python.exe -m pytest tests/unit/test_herosweb_native_capture.py tests/integration/test_herosweb_adapter_browser.py --basetemp "$env:TEMP\hweb-profile-affected" -q --tb=short` — exit 0, 96 passed, 0 skipped, 5 existing pytest-asyncio deprecation warnings, 260.95 s. The A fixture uses preloaded per-slot HTML image sources so the observed draw-before-slide geometry remains synchronous; B's reused source canvas is checked against distinct saved RGBA snapshots.
- Changed-path Ruff and `py_compile` passed for adapter.py, native_capture.py and the two changed test files. `git diff --check` exited 0; Git emitted only existing LF-to-CRLF advisories for runbook Markdown.
## A09 checkpoint — 2026-11-23 (historical; superseded by A10/B10)

The A09 standard A attempt failed before encoder or capture with `HERO'S WEB Viewer layout is not the observed RTL spread`. The recorder retained the exact `_parse_layout` input: `output/herosweb_experiment/native-independent/proofs/live20261123A09full01/herosweb-dca88b215773f/parse-layout-audit.json`.

- The failure snapshot had one required root mode missing, exactly `mode-has-pr`; canonical URL, free/header proof and other required modes were valid. Its 17 wrapper roles were 1 lead, 10 body, 1 CI, 3 PR, Good and Last. Public seek was min 1 / max 17 / step 2 / value 13. Body slots 4 and 5, plus next slot 6, were `mode-loading mode-req-render`; no wrapper had a canvas.
- At the A09 checkpoint, the initialization wait recognized only the exact resumed A layout shape: seek 13/17, 10 body roles, loading slots 4–6, no canvases and only `mode-has-pr` absent. A shallow copy with that one token added is passed to the strict parser to validate the rest of the structure; it is never accepted, frozen or captured. The adapter waits under the existing deadline and rechecks URL, header, gate and route/access guards until the actual PR mode appears. It then freezes the real snapshot and follows the existing rewind-to-first-body path. The draw-time missing-PR exception remains limited to the initial max-seek/pair-start-0 case.
- Permanent missing PR in the resumed state times out without pages; a second missing required root mode fails immediately. The success regression hydrates the real PR flag, rewinds to seek 17, then captures the first body and spread natively. It is parameterized over the observed episode and another valid episode ID with the same exact layout signature.
- Final full affected run before removing a redundant episode-ID check: `.venv\Scripts\python.exe -X utf8 -m pytest tests/unit/test_herosweb_native_capture.py tests/integration/test_herosweb_adapter_browser.py --basetemp "$env:TEMP\hweb-a09-final" -q --tb=short` — exit 0, 81 passed, 0 skipped, 5 existing asyncio warnings, 212.12 s. After the identity-neutral refinement, the resumed success/timeout/unknown-mode cases passed: 4 passed, 0 skipped, 5 warnings, 13.83 s. Changed-path Ruff, `py_compile` and `git diff --check` pass.
- A09 metrics: 582 requests, all HTTP 200, zero retries, and no observed 403/429/5xx, challenge or CAPTCHA. There were zero image/page inputs, no END/ZIP/Artifact, and no B attempt. Sources/resources/items remain unchanged; the three prior Artifacts remain preserved. No production relaxation outside the exact initialization wait was made. Source re-review was pending at this historical checkpoint and later passed; no A09 live run occurred after that fix.

## A08 checkpoint — 2026-11-23 (historical; superseded by A09)

The post-A07 standard A run (Run 12) stopped before encoder/capture with `HERO'S WEB Viewer layout is not the observed RTL spread`. No page input, capture ledger, END, ZIP, or B run was produced. Metrics recorded 582 requests, all HTTP 200, zero retries, and no observed 403/429/5xx, challenge, or CAPTCHA. The current free-entry proof and guarded route were valid.

- Evidence: `output/herosweb_experiment/native-independent/live-20261123-02/proofs/A08-layout-failure-audit.json`. The exact snapshot passed to `_parse_layout` at failure was not saved; therefore the missing or mismatching field is UNKNOWN. No layout guard was relaxed.
- A later error-state HTML snapshot showed the required RTL root classes, 17 wrappers (1 lead, 10 body, 1 CI, 3 PR, Good, Last), and seek min=1/max=17/step=2/value=1 with body wrappers in `mode-loading`/`mode-req-render`. A screenshot from a different timestamp displayed a 5/17 badge. This may indicate transient loading, but it does not establish the cause of the earlier exception.
- Tester is preparing an ignored passive recorder for the exact `_parse_layout` input before any next authorized run. No new live run is authorized here. The source/config freeze remains unchanged.
- Catalog still has 108 sources with the prior 84 free / 20 quota / 4 paid classification; source/resource/item fields are unchanged. The three existing Artifacts remain preserved. Run 12 has no pages or Artifact; B was not started.

## A07 implementation checkpoint — 2026-11-23 (historical; A09 supersedes live status)

The A07 diagnostic showed exact native-source draws for body slots 2/3 at public seek 15 while their wrappers were offscreen. The previous 98% viewport-intersection check at draw time rejected those otherwise valid candidates. This is an observed draw-location fact, not a hypothesis about inactive prefetch.

- Draw-time eligibility now binds the unique viewer tree, body wrapper, current public seek and logical spread, and retains at most two candidates for that current spread. A spread change clears them; any write or reset invalidates the prior candidate for that target.
- Draw-time geometry and target identity are recorded before the slide moves. Materialization still requires the final exact frozen layout, matching seek/owner/slots, loaded/rendered body, 98% final visibility, stable target epoch/generation/pixels, replay/VP8L proof, and a common draw-to-final translation. Geometry comparison uses a 0.001 CSS-pixel rounding epsilon.
- The sole draw-time mode exception is the observed initial shell with `mode-has-pr` pending, restricted to the initial seek maximum and pair start 0. The final frozen layout must include `mode-has-pr`; later pairs require it at draw time. All other role, mode, identity and capture checks remain strict.
- Final affected command: `.venv\Scripts\python.exe -X utf8 -m pytest tests/unit/test_herosweb_native_capture.py tests/integration/test_herosweb_adapter_browser.py --basetemp "$env:TEMP\hweb-a07-final" -q --tb=short` — exit 0, 78 passed, 0 skipped, 5 existing pytest-asyncio deprecation warnings, 203.11 s. The delayed-PR fixture interpolation error was corrected; both hydration and initial-pair native regressions pass.
- Independent source review passed with BLOCKING 0. At the original A07 checkpoint, no post-fix live run had yet occurred; the later A08/A09 results are recorded above. A06 was the latest successful full live result at that historical checkpoint; A10/B10 are current and described earlier. Original JPEG restoration remains unproven. Existing A03/A05/A06 artifacts and Phase 05 evidence are unchanged.
- No ticket, wait, coin, purchase, login, checkout, rights action, or live browser request was performed for A07 implementation verification.

## A05/A06 detailed checkpoint — 2026-11-23 (historical; superseded by A07 above)

- Phases 01–05 are closed PASS / BLOCKING 0. Their isolated Catalog, CLI, END, ZIP and artifact evidence remains valid. The two early Phase 05 HTTP 429 runs remain failed historical Runs 1 and 2; successful A/B Runs 3 and 4 are independently audited.
- Phase 04 selects only available `free` rows with `direct`; quota, paid, unknown, owned, rental, grant and unavailable rows are skipped. No ticket/resource pass or entitlement mutation is implemented. Adapter metadata provides genre `漫画` while preserving explicit request metadata precedence.
- Phase 06 diagnostic evidence: `output/herosweb_experiment/native-followup/A-4fe9831c6f540-attempt-02/diagnostic.json`. At the first A body, an immutable 1440×2048 source-canvas snapshot replayed exactly to the 934×1329 displayed target. The observed 16-tile map covered a 4×4 grid of 360×512 tiles. Target node, slot, epoch, generation, seek and pixels were stable across materialization; draw counters were unchanged. The JPEG reconstruction helper accepted no candidate. No raw JPEG body or signed URL was retained.
- Production native capture is site-local. It gates on exact current Work/episode and free entry, the frozen viewer body/target, sRGB/unorm8, source generation and complete grid geometry. It checks replay and post-materialization target state; ambiguous/unsupported proofs use the existing rendered-PNG path. A WebP is retained only when it is VP8L and decoded RGBA equals the verified native source; verified native PNG remains available if WebP validation fails. A single in-flight materializer bounds retained snapshots. Original bytes are not claimed.
- Latest full command after the A05 fix: `.venv\Scripts\python.exe -X utf8 -m pytest tests/unit/test_herosweb_native_capture.py tests/integration/test_herosweb_adapter_browser.py --basetemp "$env:TEMP\hwebnavsignaturefull20261123" -q --tb=short` — exit 0, 67 passed, 0 skipped, 5 existing Python 3.14 asyncio deprecation warnings, 213.32 s. Changed-path Ruff passed; `py_compile`, `git diff --check` and independent source review passed.
- Post-change live attempts: Run 5 failed locally with Windows `WinError 206` before HTTP; Run 6 was blocked by sandbox `permission_denied` on the main-document fetch (HTTP 0). Run 7 (A03), using the approved network execution path, reached the directly free A episode and made 589 requests with no observed 403/429/5xx, challenge, or retry. Its first-body native PNG plus production VP8L materialization succeeded, but capture stopped before a manifest page. A04 then persisted the first-body native WebP. A05 full stopped before any manifest page, END, or ZIP.
- A05 signature evidence: `output/herosweb_experiment/native-independent/live-20261123-02/proofs/A05-full-failure-audit.json` and `output/herosweb_experiment/native-independent/proofs/live20261123A05full01/herosweb-dca88b215773f/capture-signature-audit.json`. The detailed trace proves the only signature difference was `mode-nav-open` disappearing from the root class tokens: `[mode-first-page, mode-nav-open, mode-top-pr-page]` became `[mode-first-page, mode-top-pr-page]`. All wrapper/canvas IDs, dimensions, geometry, epochs, generation, seek and active-body fields matched. This is observed navigation UI auto-hide, not an inactive-prefetch hypothesis.
- The separate A03 partial audit is `output/herosweb_experiment/native-independent/live-20261123-02/proofs/A03-partial-audit.json`; its source reference and offline WebP reproduction evidence are under `output/herosweb_experiment/native-independent/proofs/live20261123A03/`. The A05 local WebP reproduction confirms its recreated SHA matched the recorded encoder result and decoded RGBA matched recorded native source. These are partial first-body proofs, not completed live capture. Catalog sources/resources remained unchanged; the two accepted Phase 05 Artifacts are preserved.
- Approved correction: only a whole capture group whose every page is `source_canvas_lossless_vp8l` or verified `source_canvas_native_png` may compare shallow-copied signatures with exactly `mode-nav-open` removed from `rootClassTokens`. Global observation signatures, readiness, transition and END checks stay unchanged; rendered PNG/screenshot groups and every other field remain strict. Added positive navigation auto-hide and negative seek, other-root-mode, target-drift and PNG-fallback cases. Focused browser tests: exit 0, 5 passed, 5 existing asyncio warnings, 17.28 s. The 67-test full suite and independent source re-review passed before A06; A06 below is the post-fix live result.
- A06 standard A CLI live run succeeded at END and produced 10 pages, Catalog Run 10, completed Item 21, and present Artifact 3. Native acceptance failed: slot 1 was VP8L at 1440×2048, while slots 2–10 were rendered PNG at 934×1329. Six encoder calls occurred; later results were all `None`. Metrics: 629 requests, 0 retries, 403/429/5xx, challenges or CAPTCHAs. No B was run. The 108-source Catalog/resources/identity fields were unchanged; the earlier two Artifacts and failed Runs remain preserved.
- A06 audit: `output/herosweb_experiment/native-independent/live-20261123-02/proofs/A06-completed-native-coverage-audit.json`. Packaging removed the manifest/progress files before they could be copied, so independent durable per-page identity and END verification remains incomplete despite the succeeded Run/ZIP/Catalog state. Tester is preparing a pre-package proof copy for any future full run.
- A07 later established one concrete rejection cause: body slots 2/3 were drawn at seek 15 while offscreen, so the previous draw-time 98% visibility gate rejected those valid draw records. The new acquisition path addresses that case, but does not establish why all other A06 later pages lacked native output. Cache/history and source-type explanations remain unproven. Earlier jump-seek observations prove high-resolution native candidates at slots 1/6/7/10, not sequential capture. No post-A07 live lease is active. The complete repository test suite was not run. The accepted Phase 05 independent audit remains at `output/herosweb_experiment/phase05-independent/proofs/20261123/phase05-final-independent-audit.json`.
- No ticket, wait, coin, purchase, login, checkout, or rights action was performed. No normal Catalog/output was used. Branch `feat/herosweb-free` remains based on `main` at `ec0afc3`; no merge or commit was performed.

## Phase 06 source-native implementation checkpoint — historical base, superseded by B14

The earlier diagnostic records below are historical evidence, not a pending approval request. At this initial implementation checkpoint, a bounded A first-body diagnostic and independent evidence/design review authorized the native implementation. A06 standard A Batch had reached END and ZIP/Catalog completion but native coverage was incomplete; later A10 and B14 full audits supersede that checkpoint.

- Current code changes are limited to `herosweb/adapter.py` and the new site-local `herosweb/native_capture.py`, with focused unit/browser tests. No Core, shared model, other adapter, or runtime configuration was changed for Phase 06.
- The observer copies eligible mutable source pixels at draw time without hashing, encoding or network work in the draw hook. It binds the snapshot to exact source/target nodes, slot, seek, generation, draw epoch/arguments and context. Coordinates must be finite exact integers on the two audited grids: 360×512 within the 1440×2048 A source, or 211×300 within the 844×1200 B source; unsupported or incomplete proof falls back to rendered PNG.
- Source and target readback require observed sRGB/unorm8. The current profile and class/layout gates are checked before materialization. Exact source replay and target pixels are checked again after asynchronous materialization. Identity/access/target drift is fatal; bounded native timeout/materialization errors may use the independent PNG path after normal route/header/guard checks. Concurrent native materialization is rejected as busy, and cleanup only removes the same selected candidate.
- A verified source is encoded as lossless VP8L WebP only if dimensions and decoded RGBA match; a verified native PNG is retained if WebP validation fails. The proof records native pixels, not original bytes. No raw JPEG body or signed URL enters the manifest.
- The native implementation and A/B profile extension passed the final affected suite (96 passed, 0 skipped, 5 existing asyncio deprecation warnings), changed-path Ruff, `py_compile`, `git diff --check`, and independent source re-review. A10 and B14 subsequently passed full native capture audits; see the current B14 checkpoint above. A05/A06 details in this section are historical.
- The bounded attempt-02 evidence path is `output/herosweb_experiment/native-followup/A-4fe9831c6f540-attempt-02/diagnostic.json`. The natural JPEG reconstruction candidate was not accepted. Original-byte restoration remains a separate unimplemented follow-up, not an inference that restoration is impossible.

## Phase 01 checkpoint — 2026-11-22 (historical probe record; later evidence below supersedes noted unknowns)

Implementation branch: `feat/herosweb-free`, based on `main` at `ec0afc3`.
Phase 02 is the current implementation scope. Live access used the existing
shared CDP endpoint `http://127.0.0.1:9222` through Playwright Python; each
probe page was closed and the remote Chrome process left running. No ticket,
wait, coin, account registration, or login action was used.

### Observed current-site identity and full-list routes

- `https://heros-web.com/series/dca88b215773f` returned HTTP 200 with the same
  canonical route and work title 「サヴマ」.
- `https://heros-web.com/series/0f023839d7bca` returned HTTP 200 with the same
  canonical route and work title 「神無き世界のカミサマ活動」.
- A work's default `/series/<work>` page contained only 10 episode rows even
  when its range controls declared a larger inventory. It is not a complete
  enumeration. The observed numeric routes are `/series/<work>/1` for 1–21 on
  the first Work and `/series/<work>/1`, `/2`, `/3` for 1–30, 31–60, 61–87 on
  the second Work. Opening each numeric route as a fresh document produced
  exactly 21, 30, 30 and 27 rows respectively, each with unique episode IDs.
  The second Work totals 87 unique rows. During SPA clicks the prior list DOM
  remained and accumulated rows; that retained DOM/order must not be treated
  as a range result. Numeric route navigation was paced at least 3.2 seconds
  apart, with no 403/429 or challenge response observed.
- Listing row/link candidates are `.series-eplist-item` and
  `.series-eplist-item-link`; range controls are under `.series-sort`. The
  fresh-document list root is `.series-eplist-main .series-eplist-default`.
  The Reviewer confirmed this scope and requires frozen Work/title/range data,
  exact per-range counts, unique ordered IDs, two stable observations, and
  at least 3.2 seconds between numeric range loads.

Sanitized evidence metadata (no page body images, cookies, or signed query):
`output/herosweb_experiment/phase01-work-dca88b215773f.json`,
`output/herosweb_experiment/phase01-complete-ranges.json`, and
`output/herosweb_experiment/phase01-isolated-ranges.json`.

### Observed access labels and user-confirmed semantics

- User-confirmed: `無料` and `今なら無料` are intended free labels. Live rows
  place both labels in `.series-eplist-item-access-text.mode-free` within
  `.series-eplist-item-access`.
- At the earlier logged-out Phase 01 probe, the live `今なら無料` row for
  `b92706d1ebe2e` belonged to
  `0f023839d7bca`, but direct GET to `/episodes/b92706d1ebe2e` returned the
  detail page with `無料登録して読む` / `ログインして読む` actions and no
  viewer canvas in that logged-out shared session. No action was clicked. This
  was superseded by the later user-authenticated same-Work direct GET, which
  reached the reader; the production classifier still requires fresh
  same-document session/header proof.
- User-confirmed: a `C`/coin icon plus a positive numeric price means paid; the
  amount varies and `90` is not fixed. Live paid rows have an exact
  `.series-eplist-item-access-paid-item` span containing
  `/images/icons/coin.svg` and direct numeric text `90`, within
  `.series-eplist-item-access-paid`. The first Work also showed `60` beside
  the coin icon. Price must be scoped to this access container; date and likes
  are separate row data.
- The initial Phase 01 text-only pass did not identify the inline ticket SVGs;
  that “neither marker observed” statement was superseded by the later exact
  badge-container observation. The paired `eliWfIcon` / `eliIfIcon` markers
  visually matched the screenshot and are now used only to classify `quota`.
  All ticket-related execution remains deferred.
- Observed inventory counts: first Work 5 free, 2 coin-priced, 14 unlabeled;
  second Work 79 free (including `今なら無料`), 2 coin-priced and 6
  unlabeled. Unlabeled rows remain `unknown`; the sample did not establish
  their access state.

Evidence for the exact free/coin row structure is in
`output/herosweb_experiment/phase01-row-badges.json`. Current site row counts
and route results are in `output/herosweb_experiment/phase01-isolated-ranges.json`.

### Viewer and capture evidence

- Direct GET to plain-`無料` episode `/episodes/4fe9831c6f540` returned HTTP
  200. The reader uses horizontal right-to-left spread mode and a public seek
  input with `min=1`, `max=17`, `step=2`. Observed wrapper roles were: index 0
  leading empty PR; 1–10 body pages; 11 CI; 12–14 empty PR pages; 15 Good; 16
  Last. Middle seek positions exposed rendered body wrappers. At seek 1, the
  same episode URL remained, the root had `mode-last-page`, and visible
  wrapper 16 had `mode-last`; the independent Reviewer accepted this as
  actual terminal END for the observed layout. No NEXT_CONTENT action was
  taken.
- At seek 17 the root had `mode-first-page` / `mode-top-pr-page`, but the
  first body wrapper intersected the viewport by only 0.02 while neighboring
  wrappers were centered. This does not prove a stable first-body capture
  state. Phase 03 must verify wrapper identity, viewport position, rendered
  pixels, seek and root flags together before initialization or capture.
- The natural first-party `/api/book/contentsInfo` response on the exact
  episode page reports `totalPages=10` and 10 ordered result entries. The page
  also naturally emitted five JPEG candidates from
  `comicsviewer.heros-web.com` with `master-...-01.jpg` through `-05.jpg`
  paths. Renderer instrumentation saw tiled `drawImage` crops from
  1440x2048 sources into 1440x2048 intermediate canvases; the viewer exposes
  934x1329 display canvases. This supports a reconstructed/tiled path, not
  unchanged-original output. Exact source-to-visible pixel identity and
  native reconstruction are unproven; use stable body canvas PNG unless
  Phase 03 establishes stronger proof.
- Three canvas DOM nodes existed at the first state; only one intersected the
  viewport, while two were offscreen. Do not treat CSS-visible/offscreen
  prefetched canvases as body pages without checking wrapper role and position.
- There was no HERO'S WEB/CDN non-GET request on the plain-free reader. The
  current page's non-GET traffic was analytics/ads only. No access rejection,
  403/429 or challenge was observed.
- The current plain-free viewer metadata is in
  `output/herosweb_experiment/phase01-free-viewer.json`; the now-free access
  sample is in `output/herosweb_experiment/phase01-nowfree-viewer.json`. The
  latter's HTTP 400 was a GET to `/api/payment/paypay/chargeNotifications`;
  no payment or entitlement action was made. Seek and wrapper evidence is in
  `output/herosweb_experiment/phase01-viewer-structure.json`,
  `phase01-viewer-seek-sequence.json`, and
  `phase01-seek-map-and-rewind.json`.
- At this Phase 01 checkpoint, production tests had not run. The independent
  Reviewer verified fresh-range enumeration and terminal END for this layout.
  Later Phase 02 evidence below resolves authenticated `今なら無料` and the
  quota icon pair for Discovery. Stable first-body capture and source-native
  fidelity remain explicit limitations for the future Viewer phase.

Phase 02 is approved for Discovery, registration/preview wiring, site runtime
configuration, focused tests, README/note synchronization, and isolated full /
incremental Catalog verification. Ticket execution, Core changes, Catalog
schema changes, and access classifications beyond live evidence are excluded.

## Checkpoint template (append, never overwrite old factual claims)

- Timestamp, implementation branch/commit and diff scope.
- Phase, objective and finite probe allowance.
- OBSERVED, HYPOTHESIS, UNKNOWN, BLOCKED: concrete evidence (no account secrets or copyrighted page images in Git).
- Exact tested canonical URLs/Work and episode identities, current access label, role/layout/END, page count and capture modes. No signed query/cookie/token.
- Tests: command, passes/fails/skips, actual artifact location, what was NOT run and why.
- Independent Reviewer: PASS / BLOCKING and resolution, Tester evidence if used.
- Next phase and unresolved decision(s).

## Initial instruction to Codex

Read `runbooks/herosweb-free/README.md`, this file, Phase 01, the repository authorities and current Hanayume/Younganimal code. Create an isolated implementation branch from current `main`, preserve all user work, execute Phase 01 bounded current-site verification, and advance through Phases 02–05 as their evidence gates permit. Never click ticket/paid/wait or start rights acquisition, and do not assert implementation or E2E PASS until actually observed. Update this progress file and `note/16_herosweb.md` as real implementation is added.

## Phase 02 checkpoint — 2026-11-22 (historical snapshot; later Full/Incremental and B3 review PASS are recorded above)

Implementation branch: `feat/herosweb-free`, based on `main` at `ec0afc3`.
This records the earlier Phase 02 implementation checkpoint; the initial
authenticated Full failure and its corrective review evidence are preserved
here as history, while the final post-transport Full/Incremental and B3 gate
status appear in the current checkpoint above.

### OBSERVED

- Reviewer B1–B6 corrections have been implemented and covered by the focused
  suite: plain anonymous `.series-eplist` ancestry; one positive CSS-visible
  owner plus only the exact zero-area parent-hidden mirror; pre-dispatch
  main-frame GET protection; auth response binding to dispatch-time document
  generation; strict preservation and rejection of unknown access children;
  and multi-range, access-stop, preview/replay, and Catalog-preservation cases.
- The first authenticated isolated CLI Full run completed both supplied Works:
  21 rows for `dca88b215773f` and 87 rows for `0f023839d7bca`; both reported
  `complete=True`. It used `output/herosweb_experiment/phase02-watchlist.yaml`
  and the isolated pre-final-schema
  `output/herosweb_experiment/phase02-reviewfix-catalog.sqlite`.
- That pre-final-schema Catalog had 108 sources: 88 `unknown`, 20 `quota`, and
  no `free` or `paid`. This is not a passing classification result. It exposed
  incomplete access-tree matching and the latest code/fixture correction is
  based on the bounded current-DOM evidence below.
- Current bounded range-3 snapshot of Work B returned HTTP 200 with one
  authenticated owner root (27 rows) and one matching mirror. The production
  `_snapshot_script()` captured two equal observations. The access elements
  are serialized in
  `output/herosweb_experiment/phase02-access-children-diagnostic-rerun.json`.
  Plain free is marked by `data-e2e="eliFreeBadge"`; `今なら無料` by
  `data-e2e="eliMemFreeBadge"`. The paid row has an outer blank `DIV`, then
  `.series-eplist-item-access-paid`, a price span marked `eliPrice`, and a
  coin image with `alt="コイン"`, `data-e2e="eliCoinIcon"`, and
  `data-nimg`. The paired quota SVG markers were also captured; the earlier
  text-only probe had missed them and its “no ticket markers observed” summary
  is withdrawn.
- One diagnostic attempt using the production `_stable_snapshot()` stopped
  because its first two samples differed; it saved only the failure and two
  blocked `/api/missions` attempts at
  `output/herosweb_experiment/phase02-access-children-diagnostic.json`. A
  bounded second observation settled and validated matching owner/mirror rows.
  Neither probe opened an episode or triggered a rights action.
- Authenticated current-document session/header proof and direct same-Work
  now-free reading were previously confirmed for episode `b92706d1ebe2e`.
  Anonymous or stale auth remains insufficient; delayed prior-document auth is
  covered by a unit regression. The direct episode probe attempted four
  first-party POSTs (`/api/missions` ×3 and `/api/episodes/b92706d1ebe2e/read`
  ×1); the route guard aborted them before dispatch. No checkout, ticket,
  coin, login, or entitlement operation was sent.

### Validation and remaining gate

- Latest focused command:
  `.venv\Scripts\python.exe -m pytest tests/unit/test_herosweb_discovery.py tests/integration/test_herosweb_discovery_browser.py --basetemp output/herosweb_experiment/pytest-final-confirm2 -q`
  — exit 0, 21 passed, 14 existing pytest-asyncio deprecation warnings,
  33.96 s. The matching changed-path Ruff command completed exit 0 with
  `All checks passed!`.
- CLI and registration group:
  `python -m pytest tests/unit/test_cli.py tests/unit/test_registration_draft.py tests/unit/test_registration_resolver.py tests/unit/test_registration_service.py --basetemp output/hc -q`
  — 422 passed, one optional `pykakasi` skip. An earlier run with the longer
  `output/herosweb_experiment/pytest-cli-reg` basetemp failed the unrelated
  `test_work_delete_cli_json_apply_isolated` with a Windows `FileNotFoundError`
  followed by `UnboundLocalError`; the same tests passed using short
  `output/hc`.
- A first incremental invocation was interrupted before producing a log or
  changing the isolated Catalog; it is not counted as a result. The later
  final-code Full and Incremental runs below completed successfully.

### Final-code verification and independent review

- Focused command `.venv\Scripts\python.exe -m pytest tests/unit/test_herosweb_discovery.py tests/integration/test_herosweb_discovery_browser.py --basetemp output/herosweb_experiment/pytest-final-confirm2 -q`
  — exit 0, 21 passed, 14 pytest-asyncio deprecation warnings, 33.96 s.
- Ruff command `.venv\Scripts\python.exe -m ruff check src/screenshot_crawler/site_adapters/herosweb tests/unit/test_herosweb_discovery.py tests/integration/test_herosweb_discovery_browser.py`
  completed exit 0: `All checks passed!`.
- CLI/registration command `.venv\Scripts\python.exe -m pytest tests/unit/test_cli.py tests/unit/test_registration_draft.py tests/unit/test_registration_resolver.py tests/unit/test_registration_service.py --basetemp output/hc -q`
  — exit 0, 422 passed, 1 optional `pykakasi` skip. The earlier long-temp-path
  run failed in unrelated `test_work_delete_cli_json_apply_isolated` with
  Windows `FileNotFoundError` / `UnboundLocalError`; rerunning with short
  basetemp passed.
- Final isolated commands (same arguments except mode) both exited 0:
  ```powershell
  .venv\Scripts\python.exe -m screenshot_crawler.cli discover --all --mode full --watchlist output/herosweb_experiment/phase02-watchlist.yaml --catalog output/herosweb_experiment/phase02-finalreview-catalog.sqlite --env-file .env --crawler-config crawler.yaml --cdp-endpoint http://127.0.0.1:9222
  .venv\Scripts\python.exe -m screenshot_crawler.cli discover --all --mode incremental --watchlist output/herosweb_experiment/phase02-watchlist.yaml --catalog output/herosweb_experiment/phase02-finalreview-catalog.sqlite --env-file .env --crawler-config crawler.yaml --cdp-endpoint http://127.0.0.1:9222
  ```
  Both used the isolated `output/herosweb_experiment/phase02-finalreview-catalog.sqlite`
  and existing shared CDP endpoint.
  Full reported 21/21 rows for `dca88b215773f` and 87/87 for
  `0f023839d7bca` (`complete=True`); Incremental reported 21 known and 87 known,
  zero new, both Works succeeded. Logs are
  `output/herosweb_experiment/phase02-finalreview-full.log` and
  `phase02-finalreview-incremental.log`.
- Both isolated Catalog audits found 108 unique Work-bound sources at positions
  1–21 and 1–87 with identical source/item IDs and identity-position digests
  before and after Incremental. Final access counts: 「サヴマ」 5 free / 14
  quota / 2 paid; 「神無き世界のカミサマ活動」 79 free / 6 quota / 2 paid;
  total 84 free / 20 quota / 4 paid / 0 unknown. Audit artifacts are
  `phase02-finalreview-full-catalog-audit.json` and
  `phase02-finalreview-incremental-catalog-audit.json` under
  `output/herosweb_experiment/`.
- Final independent code review and independent live audit: PASS, BLOCKING 0.
  The adapter README, site note and this progress record now agree on the
  anonymous wrapper ancestry, authenticated mirror rule, exact access markers,
  and final inventory/classification results. Phase 02 passed independent code
  and live review; the later Phase 03 routing review reopened B3 for a site-local
  exact-main-document redirect guard and regression. Phase 03 is in progress.
  No merge or commit was performed.

## Phase 02–03 checkpoint — 2026-11-22 (historical; superseded by the Phase 04 checkpoint above)

### Phase 02 post-transport Full and Incremental

- Full command: `.venv\Scripts\python.exe -X utf8 -m screenshot_crawler.cli discover --all --mode full --watchlist output/herosweb_experiment/phase02-watchlist.yaml --catalog output/herosweb_experiment/phase02-post-authwait-catalog.sqlite --env-file .env --crawler-config crawler.yaml --cdp-endpoint http://127.0.0.1:9222`; process exit 0, Work A 21/21 and Work B 87/87, both complete.
- Incremental used the same command with `--mode incremental`; process exit 0, A 21 known / 0 new and B 87 known / 0 new; both succeeded.
- Catalog audits: `output/herosweb_experiment/phase02-finalreview-postauth-full-catalog-audit.json` and `output/herosweb_experiment/phase02-finalreview-postauth-incremental-catalog-audit.json`. Both contain 108 unique Work-bound rows, complete positions 1–21 and 1–87, counts 84 free / 20 quota / 4 paid / 0 unknown, unique Source/Item IDs, and matching identity-position, Catalog-row and inventory digests. Isolated Catalog: `output/herosweb_experiment/phase02-post-authwait-catalog.sqlite`.
- The reruns exercise the exact-main-document no-redirect transport and the bounded positive-session header hydration added to Discovery. No HTTP rejection/challenge was observed; the existing AccessGuard remains authoritative.

### Phase 03 real Runner and artifacts

- A full Runner output: `output/herosweb_experiment/phase03-A-full-run-20261122/`; independent audit PASS: `output/herosweb_experiment/independent_audit/phase03-A-full-audit.json`. Exact free proof for Work `dca88b215773f` / episode `4fe9831c6f540`, 10/10 body slots, actual terminal END, ten ordered nonempty PNGs and valid ZIP. The original driver wrote a complete archive/audit but exited 1 on final Japanese stdout under CP932; independent audit verified the persisted artifact. No site rerun was needed.
- B full Runner output: `output/herosweb_experiment/phase03-B-full-run-auth-hydration-20261122/`; fresh auth evidence: `output/herosweb_experiment/phase03-B-auth-diagnostic-retry.json`; independent audit PASS: `output/herosweb_experiment/independent_audit/phase03-B-full-audit.json`. Exact authenticated same-Work `今なら無料` proof for Work `0f023839d7bca` / episode `b92706d1ebe2e`, 38/38 body slots, actual terminal END, 38 ordered PNG members and valid ZIP. Header hydration was awaited passively only after a positive current-document session user.
- Both audits validate manifest-order ZIP members, CRC, decoded RGBA dimensions and SHA, spread/body order, capture proof snapshots and END coverage. Capture is `rendered_canvas_png`; source-native/original mapping is still unproven. At that checkpoint, the A/B package path fell back to `小説`; Phase 04 now supplies comic genre metadata for new Batch output without changing capture proof.
- A first B attempt stopped before capture because the positive session header had not yet hydrated; it is preserved separately at `output/herosweb_experiment/phase03-B-full-run-20261122/`. The later bounded same-range read-only auth diagnostic proved session user presence and stable header hydration; the single approved Runner retry then passed. No retry after access rejection occurred.

### Tests, reviews and remaining gates

- Latest Discovery unit/browser command, run independently by Lead: `.venv\Scripts\python.exe -m pytest tests/unit/test_herosweb_discovery.py tests/integration/test_herosweb_discovery_browser.py --basetemp "$env:TEMP\hha20261122" -q --tb=short`; exit 0, 43 passed, 0 skipped, 77 existing Python 3.14 asyncio deprecation warnings, 36.13 s.
- Latest focused current-document auth hydration tests: 3 passed, 0 skipped; includes Viewer and Discovery delayed-positive-header cases plus anonymous denial. Earlier full HERO targeted selection passed 84 tests, 0 skipped, before the bounded hydration adjustment. CLI/registration group passed 422 tests with 1 optional `pykakasi` skip. Changed-path Ruff passed.
- A/B source and artifact review passed with zero blocking findings. At this checkpoint, Phase 04 Batch policy and Phase 05 standard CLI E2E had not started; the later Phase 05 checkpoint above supersedes that historical status. The branch remains unmerged.
- Native/original capture remains deliberately unclaimed; no ticket or paid action was used.
- Historical follow-up authorization after Phase 05 led to the A10/B14 source-native implementation and live audits described above. Original JPEG-byte recovery remains unimplemented and unproven; the prior reconstruction probe accepting no candidate does not prove recovery impossible.
- Reviewed runtime source SHA-256 checkpoint (loaded from this worktree's `.venv`): `src/screenshot_crawler/site_adapters/herosweb/adapter.py` `45a6eed1f48e8abd319b32c798315d374e25a1e57f06193fd90297cef9fd2e0f`; `discovery.py` `f3f105a7e3ceea116a557455589daa769dc9b540c74b80137b73aebdb236aa61`. Browser/unit test SHA-256: adapter browser `68c9d7cab3299fe77406316a81a54b0c891246564301d7d5be928ed52ec69535`; Discovery browser `22716539c51ba74f5f360d0ea19afb2aa19b0ae36daec155830dfdfe78a19d25`; Discovery unit `e3066fab18fdef1f8cd1bd2f33973ab0a2f859a4e7c6dc8ea7b2dbfb2a9b4cab`. Runtime modules resolved to this worktree under `src/screenshot_crawler/site_adapters/herosweb/`; CLI and live Runner commands were invoked with `.venv\Scripts\python.exe` from the worktree root. The ignored A/B driver scripts contain no `PYTHONPATH` or `sys.path` override.
