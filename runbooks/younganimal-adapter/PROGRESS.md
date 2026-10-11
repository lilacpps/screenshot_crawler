# Young Animal Web Adapter — Progress

Date: 2026-10-11
Branch: `feat/younganimal-adapter`
Base: `main` @ `43d9218`
Status: **Phase 01 VERIFIED; Phase 02 partial Discovery code/tests/docs VERIFIED by Reviewer (BLOCKING 0) and local checks PASS; complete live Discovery INCOMPLETE (HTTP 429, corrected code not live). Phase 03-04 NOT IMPLEMENTED; Phase 05 documentation/unknown-only, wait NOT IMPLEMENTED; Phase 06 local audit PASS, live E2E INCOMPLETE. No human approval is pending; the live stop is external.**

## Confirmed user preferences
- `younganimal` は花とゆめ＋と別サイト。
- 実装対象: **「無料」「待つと無料」**。チケットは将来。
- 両サイトのIDは共通、ログインは別。セッション・権利の共有は未実証。
- **完全に独立したsite adapterの実装を許容**。共通化の義務なし。
- Hanayumeの初期状態、Catalog直接Viewer入場、native source capture/WebPを積極的に参考にする。

## Research handoff
前回Probeは無料token候補2作品、Viewer初期表示1話、表示Canvas925x1329に留まった。
本Phase01でユーザー指定話のcanonical work、row-scoped exact label、初期/中間のViewer状態を追加確認した。
全件Discovery、待機状態、最終本文ページのidentity、native pixel一致は未検証。
2話目のgoto 30秒timeoutとcleanup中断の原因は不明のままである。
[Previous research evidence](https://github.com/lilacpps/screenshot_crawler/blob/research/younganimal-comici-compat/runbooks/younganimal-compat/EVIDENCE.md)。
実装参考のHanayumeは現行mainのR8/R9/R10を確認した。Younganimalへ既知寸法やlayoutを転用しない。

## Phase status

| Phase | Status | Minimum proof before acceptance |
| --- | --- | --- |
| 01 Site Probe | VERIFIED | Reviewer PASS / BLOCKING 0。終端は未保存console観測として明示し、durable claimから外した |
| 02 Discovery | PARTIAL IMPLEMENTATION VERIFIED; REVIEWER BLOCKING 0; LOCAL PASS; LIVE COMPLETE DISCOVERY INCOMPLETE (HTTP 429; corrected code not live) | strict series seed / conservative history handling / complete live 925 rows remain unverified |
| 03 Viewer/Capture | BLOCKED / NOT IMPLEMENTED | normal body sequence, END, original/native/Canvas attribution and quality remain unproven; no live request after HTTP 429 |
| 04 Free direct Batch | BLOCKED / NOT IMPLEMENTED | requires accepted complete Discovery and Phase 03 Viewer/Capture proof |
| 05 Wait-free | DOCUMENTATION / UNKNOWN-ONLY CLASSIFICATION; WAIT NOT IMPLEMENTED | live state and non-consuming entitlement/resource semantics remain unverified |
| 06 Independent E2E | LOCAL TEST/AUDIT PASS; LIVE E2E INCOMPLETE | Tester local PASS; no live capture, ZIP, entitlement state, or complete Catalog flow verified |

## Phase 01 checkpoint — bounded live probe (2026-10-11)

- Commit at probe start: `805ad18a488bfd24f91240c6099094ffa9e815e7`。Tracked changes are limited to this progress file and the Phase 01 runbook status. Probe scripts and metadata reports are under ignored `output/younganimal_experiment/`; they are not commit candidates.
- Browser: existing shared Crawler Chrome via repository `BrowserSession` / CDP, one owned Page at a time. The supplied target returned HTTP 200. No 403/429, CAPTCHA, or challenge signal was observed. The owned pages were closed; a reload after the bounded seek returned to its initial seek value 21.
- Canonical identity: `https://younganimal.com/episodes/55889b8a851cb` is `PART.1` of `ふたりエッチ`; its unique `a.ep-h-main-h-series` resolves to `/series/aee4fa742b0fe`.
- Exact access label: on that canonical series page the exact target route is a `.series-eplist-item`; inside the same row, `span.series-eplist-item-access-text.mode-free` contains exactly `無料`. Other observed rows in the same initially rendered subset contain exactly `今なら無料` under the same class. The shared class does not distinguish entitlement semantics; labels are read as exact row text.
- Listing extent: the page exposes 31 contiguous range links from `1-30` through `901-925`, plus a visible `.series-eplist-loader-btn` labeled `もっと見る`. Only 10 episode rows were present in the initial DOM, so the complete listing, expansion behavior, exact range routes, and global ordering remain for Phase 02. No loader/range control was clicked in Phase 01.
- Authentication: a visible `ログイン` anchor and a favorite link with class `mode-not-user` were present. Their auth meaning was not independently verified against a logged-in positive state, so login state and any relationship with Hanayume remain UNKNOWN. No login/account control was touched.
- Viewer initial state: `#comici-viewer` has `mode-spread mode-first-page mode-top-pr-page`. `#xCVSeekBar` is a public range input with value 21, min 1, max 21, step 2. `#xCVPages` has 22 direct physical wrappers. Slot 0 is `mode-empty mode-pr mode-top-pr` with no canvas; slots 1–3 were initially loaded/rendered. Tail observations include `#xCVComicInfoPage.mode-ci`, two empty PR slots, `#xCVGoodPage.mode-good`, and `#xCVLastPage.mode-last`. No textual current/total counter was found; exact body-slot mapping and normal final-advance behavior remain UNKNOWN.
- Bounded navigation: the durable `phase01_viewer_positions.json` report records value 11 with active wrapper slots 9–11 and without `mode-first-page`; it records the reload state as value 21. In an earlier probe run, five `ArrowLeft` presses on the focused public `#xCVSeekBar` moved the value from 21 to 1; the console summary at that time showed `#comici-viewer.mode-last-page`, active slots 19–21, and `#xCVLastPage` intersecting the viewport. That terminal observation was not retained in the JSON report and was overwritten by the later run. **There is no durable terminal-state evidence in the current probe artifacts.** No `#nextArrow`, episode, access, wait, purchase, or ticket control was activated. Verify the terminal state in Phase 03 if needed for its capture contract.
- Canvas / source evidence: the first-state rendered canvases had bitmap dimensions 984×1329 and CSS bounds 656×886. A pre-navigation `drawImage` trace saw three unique WebP source path signatures, each 960×1297; source-to-intermediate draws used 4×4 tiles of 240×324 into 960×1296 targets (the source height includes one row beyond that target). Seven later canvas-to-canvas draws scaled 960×1296 to 984×1329. This is sampled transport/draw evidence only: source-to-final page identity, full tile map/reconstruction equality, original JPEG identity, source-native pixel equality, and stable capture are not proven. The observed JPEG responses were not linked to body canvases; do not pursue DCT restoration for this sample without new attribution evidence.
- Wait-free: no exact `待つと無料` row or wait state was observed. `今なら無料` is an observed label only; waiting eligibility, timer, release, and resource semantics remain UNKNOWN. No wait/entitlement action was performed.
- Access/source identity and output: only the user-provided free-labeled target was opened. No Catalog, Watchlist, normal output, or tracked image/HTML artifact was written. Probe files in ignored output contain metadata only, with URL queries omitted.
- Validation: live metadata probes ran from `output/younganimal_experiment/phase01_probe.py` and `phase01_viewer_positions.py`. No pytest/Ruff was run because no production or test code changed. Other-site regression, full suite, and Tester audit were not applicable to this research-only checkpoint.
- Reviewer: Phase 01 VERIFIED by Lead after independent review, BLOCKING 0. Reviewer specifically found the terminal output was not durable; docs were corrected. Tester: NOT RUN.
- Phase 01 decision: exact row text `無料` is the only current positive free classification. `今なら無料`, `待つと無料`, blank, conflicting, or unrecognized labels remain unknown until Phase 05 establishes additional state semantics.
- Next: Phase 02 is authorized. Implement only Younganimal Discovery/access logic, focused tests, registry, README/note. No Core/schema/Hanayume changes. Phase 03 must establish page/body mapping, last body vs END, and source/canvas identity before production capture support.

## Phase 02 contract — Discovery (2026-10-11)

- Lead gate: Phase 01 VERIFIED / BLOCKING 0. Implementer remains the sole production writer and shared Chrome operator.
- Goal: discover the complete Younganimal work through observed canonical `/series/<work-id>` and declared range/loader UI; validate every page and buffer the complete work before yielding any record.
- Identity: strict exact canonical first-party series URL shape `https://younganimal.com/series/<13-lowercase-hex-work-id>` only; the observed target example resolves to work `aee4fa742b0fe`. Episode URLs remain row identities and bounded-scope boundaries, but are rejected as seeds before navigation.
- Access: only one exact row-scoped `無料` positive label maps to `free`. `今なら無料`, `待つと無料`, absent, duplicate/conflicting, unknown, or nonexact labels map to `unknown`; do not infer wait grants or auth from IDs/session markers.
- Completeness: require declared range coverage, expected per-range counts, unique episode IDs, one consistent work title, and oldest-first global positions. No episode-seed containment is claimed. Full/incremental modes buffer the complete listing before Catalog synchronization; bounded slices retain whole-work positions.
- Failure safety: route drift, guard/challenge/429/403, unknown range/page state, unsupported nonempty history rows, missing rows, duplicates, overlap disagreement, timeout, or incomplete traversal raises the existing Discovery failure contract before any episode records are yielded; no incomplete listing may mark unseen sources unavailable.
- Scope: Younganimal discovery/access module, minimal Discovery CLI registry, site tests, site README, `note/11_younganimal.md`, this runbook checkpoint. No generic Core, Catalog schema, Hanayume, Batch, Viewer, or capture change.
- Validation: targeted discovery/access Unit; browser-backed Discovery Integration; existing Hanayume Discovery and CLI registry tests; bounded live full-work traversal with explicit isolated watchlist/Catalog/output. Ruff for changed Python files.
- Uncertainties carried forward: complete row and range-route semantics are pending Probe; `今なら無料` wait/entitlement meaning belongs to Phase 05; page/native capture evidence belongs to Phase 03.

## Phase 02 checkpoint - implementation and bounded live result (2026-10-11)

- Changed paths: Younganimal `access.py` / `discovery.py` / package init; Discovery-only CLI registration; focused Unit and synthetic Playwright Integration tests; CLI registry test; site README; `note/11_younganimal.md`; minimal `note/00_core.md` registry note; Phase 01/02 runbooks and this progress file. No shared Core, Catalog schema, Hanayume, Viewer, Batch, or capture production code changed.
- OBSERVED: the target work is `aee4fa742b0fe`; its listing declares 31 numeric ranges (`1-30` through `901-925`). Fresh `/1` returned 30 rows/30 unique IDs and its selected `1-30` link pointed to the canonical work root. Bounded samples `/2` and `/3` through `/5` returned 30 rows each. The canonical listing showed one exact latest control, 31 numeric routes, and one href-less ellipsis.
- OBSERVED: both isolated DiscoveryService databases contain one Work row created before adapter invocation and zero items, episode sources, targets, runs, artifacts, or quota states. No episode records were yielded; the normal Catalog was untouched. The 90-second diagnostic harness stopped at `/28` without a completed result or proving an AccessGuard cause.
- OBSERVED: the final 180-second-capped traversal, using the earlier episode-seed draft before the current review fixes, stopped after nine range pages (11 navigations total) in 13.066 seconds when AccessGuard observed HTTP `429` at `/series/aee4fa742b0fe/9`. No episode records were yielded. `Retry-After` was not retained. No request, retry, alternate endpoint, or profile use followed the 429. The 925-row contract remains unverified; current corrected code has no live verification.
- IMPLEMENTED: exact canonical series-seed validation before guard startup/navigation; episode-seed rejection; strict range parsing; observed pagination controls; exact row-scoped free classification; complete buffering; global positions; bounded cleanup; nonempty `epListUser` history rejection because duplicate identity/title/access semantics are unverified. Wait/resource state is not implemented.
- UNKNOWN: why earlier bounded AccessGuard checks timed out; complete route/count/ID/order consistency across all 925 rows; terminal Viewer/body/END mapping; original/native source attribution; waiting/resource semantics. No cause is inferred from later fast checks.
- Validation: targeted Younganimal suite `28 passed, 23 warnings` (existing pytest-asyncio deprecations); Tester ran the two Younganimal files independently: `27 passed, 0 skipped, 23 warnings` in 4.31s. `ruff check src tests` passed. Lead-run regressions: Hanayume group `201 passed, 0 skipped`; generic CLI/registry/discovery/catalog/watchlist group `214 passed, 0 skipped`; the focused Younganimal CLI registry test overlaps only the generic group.
- Phase 02 decision: final Reviewer verified the partial Discovery implementation/tests/docs with BLOCKING 0. Complete 925-row live Discovery is still **not verified**, and the corrected canonical-series-seed/history-rejection implementation has not been live-tested. The final live run used the earlier episode-seed draft and stopped at HTTP 429; no requests followed. The external site stop is the sole live blocker; no human approval is pending. Phase 03/04 remain NOT IMPLEMENTED, Phase 05 remains documentation/unknown-only with waiting NOT IMPLEMENTED, and Phase 06 is local-only with E2E incomplete.
- Reviewer: Phase 02 partial Discovery code/tests/docs VERIFIED, BLOCKING 0. Tester: local audit PASS (`27 passed, 0 skipped`, 23 existing warnings, 4.31s); read-only isolated Catalogs each have one Work row and zero other records, JSON sanitation passed, and there were no post-429 site calls.

## Checkpoint contract
各Phase後、以下を追記:
- Date, commit, changed paths, design decision:
- OBSERVED / INFERRED / UNKNOWN:
- Access states, click/consumption and source identity:
- Native JPEG/DCT/source canvas/rendered fallback evidence:
- Unit/Integration/live tests, pass/fail/skip/reasons:
- Reviewer BLOCKING/NON-BLOCKING/VERIFIED:
- Tester PASS/FAIL/NOT VERIFIED:
- Other-site regression and docs/note status:
- Next action, human decision needed (max 3):

重要: Free E2E成功後も`待つと無料`を調査・実装する。待機の実例不足や権利操作の
ブロッカーがあれば部分完成を正確に報告して分離。無実証の大きな共通化はしない。
