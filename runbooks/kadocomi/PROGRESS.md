# Kadocomi Free-Only Adapter - Progress / evidence ledger

Status: P1 Discovery and P2 capture passed independent review (BLOCKING=0) and
bounded live validation. P3 direct-only policy, CLI registrations, and local
Catalog-to-ZIP integration passed targeted and affected tests and independent
review (BLOCKING=0). P4 live CLI Batch and independent
archive/completion audit have not started. Unverified layouts are not recorded
as success.

## Stage checkpoints

| Stage | Status | Evidence / remaining work |
| --- | --- | --- |
| P0 Site and source research | CONTRACT PASS | Exact 53 episode rows plus one explicit ended-publication marker in the public UL; anonymous work/episode identity; target-scoped no-deadline proof; source-to-draw WebP proof; reader END observed. Exact historical episode set remains unknown. |
| P1 Discovery | PASS | Strict scoped list parser, exact known ended-publication placeholder handling, history-safe full/incremental behavior, 18 focused passes, isolated live full/incremental validation, independent Reviewer BLOCKING=0. |
| P1.5 Position safety | PASS | Shared opt-out hook committed as ceb3434; independent Reviewer BLOCKING=0; 51 passed / 0 skipped. Kadocomi opts out and its persistence behavior is covered in P1 integration. |
| P2 Viewer/Capture | PASS | Corrected production Runner captured all 21 source-native WebP pages through explicit END; independent review BLOCKING=0 and 16 independent targeted passes. Tester independently audited every saved page against its normal-renderer Blob and canvas with zero pixel mismatch. The separate 38-page layout remains unsupported. |
| P3 Free-only Batch / ZIP | PASS | Direct-only policy and CLI wiring, real local Catalog → Planner → Executor → Runner → ZIP/Artifact/Completed; runtime failures preserve pending. 301 affected passes and 54 independent passes; Reviewer BLOCKING=0, NONBLOCKING=0. |
| P4 Independent E2E | NOT STARTED | Fresh isolated Catalog, live run, independent image/archive audit, and Reviewer BLOCKING=0. |

## Initial target and containment

- Worktree/branch: C:/Users/kensu/projects/screenshot_crawler_kadocomi, feat/kadocomi-adapter; the original workspace dirty crawler.yaml, watchlist.yaml, and debug.log were preserved.
- Real-site probing used the already-running shared Crawler Chrome over CDP and an owned anonymous BrowserContext; only the owned context was closed. No separate browser/profile was launched.
- No login, purchase, ticket, coin, point, rental, DRM, or access-control bypass was used. No 403, 429, or CAPTCHA was encountered.
- Dedicated probe artifacts are excluded from Git. No page bodies, image bytes, credentials, cookies, or tokens are committed.

## P0 OBSERVED

- Anonymous work URL https://comic-walker.com/detail/KC_004915_S?episodeType=first returned HTTP 200. The exact episode-list parent is DIV.EpisodesTabContents_root__VrJZ1; its unique UL.EpisodesTabContents_episodeList__cIDQz settled to 53 distinct episode links, equal to the displayed 53-episode count, in two identical snapshots 500 ms apart. A duplicate teaser outside that UL was excluded.
- The visible linked sequence contains labels 1 through 26 and then 78/79. The UL has 53 episode rows plus one explicit non-episode placeholder at direct-child index 51. Its exact text is `その他の話は公開終了しました` (other episodes have ended publication), between `第26話その2` and `第78話`. This confirms an ended-publication gap marker but does not establish the exact former episode set or lifetime numbering.
- Forty-six rows show the exact Japanese delivery-deadline label with timestamp 2026/10/14 11:00; seven show no deadline. The page-level campaign banner is not row-level access evidence.
- The target chapter title is under a descendant whose class begins EpisodeThumbnail_title__. Its publication date and deadline text are separate nodes; dates do not belong in order_label.
- Work detail og:title and document.title contain the stable Work name plus Comic Walker branding. Its H1 is chapter-prefixed, so it is not the Work title. The target episode route is /detail/KC_004915_S/episodes/KC_0049150000400011_E?co=true&episodeType=first; queryless input returned the same work/episode identity, after which the site added episodeType=first.
- A second no-deadline row, KC_0049150000100011_E, was reached anonymously on the same exact work and public list. It rendered the expected episode H1 without password, CAPTCHA, expired message, or ticket/coin/point/purchase gate. Official Comic Walker help describes WEB as a free manga portal (https://help.comic-walker.com/hc/ja/articles/24221086268697); its deadline FAQ says deadlines appear only when configured and a no-deadline episode may end without notice (https://help.comic-walker.com/hc/ja/articles/24220791385241).
- On the target episode, a normal renderer hook retained five already-created Blob references while preserving the original URL.createObjectURL call. Draw-time HTMLImageElement.currentSrc mapped the exact Blob and content canvas for DOM slots 0, 1, 2, 19, and 20; observed byte lengths were 169566, 141084, 133452, 126880, and 199144, with RIFF/WEBP signatures. Five representative Blob-to-canvas full-RGBA comparisons had zero mismatches. Each observed image/canvas was 836x1200 with full-frame identity draw. These are native viewer source-image bytes, not proof that opaque network responses contain the same original bytes.
- Independent Tester clarified that the content canvas is owned by the preceding wrapper; the earlier phrase content canvas did not mean the canvas itself had `data-type="contents"`. On the first-episode variant, inactive canvases can carry 1200x1600 placeholders while active source images are 835x1200; dimensions are read and proven per active draw, never hard-coded.
- Independent Tester observed a separate first-episode layout with 38 content canvases over 21 slides: slide 1 has one content slot plus a PR item; slides 2 through 19 have pairs; slide 20 has one content slot with reader END n=2; slide 21 is empty with reader END n=1 and n=2. This is a different order/END contract from episode 4.1 and remains unsupported.
- Reader navigation through ordinary LEFToverlay clicks traversed 21 content slots over 11 right-to-left content slides while remaining on the exact episode. The 21 canvases have class `_root_bx4cr_1` and no `data-type`; each sits inside `DIV._pageCanvasWrapper_k9w27_25[data-type=contents]`. The next slide (12 of 13) exposed two `DIV._endOfBookWrapper_k9w27_34[data-type=end-of-book]` markers with `data-n="1"` and `data-n="2"`. The trailing slide has separate `_root_1w5tt_1[data-type=end]` and `_endOfBook_1w5tt_50[data-type=end-of-book]` nodes and is not the main-reader END. A separate PR element was excluded. No copyrighted pixels or source bytes were retained in repository evidence.

## P0 INFERRED, LIMITED

- Public-list membership plus official free-WEB service and a positive anonymous exact episode supports the observed public WEB row variant. Explicit future deadlines classify free; no-deadline rows classify free only for the independently verified work KC_004915_S. Other no-deadline works and expired-deadline rows remain unknown.
- Source positions must not be inferred from compact visible rank or episode IDs. Existing positions remain unchanged and new positions remain NULL until a site-wide order authority is proven.
- The retained Blob source gives a non-screenshot, source-native capture path for the observed renderer. P2 implements per-capture provenance, pixel equality, page identity/order, and safe END handling. Corrected production code passed all 21 pages through END after independent DOM diagnostics resolved its initial selector error.

## P0 UNKNOWN / NOT VERIFIED

- The exact historical episode set and lifetime ordering behind the ended-publication marker, the complete behavior of ended ranges, and whether this 53-row list is complete beyond this exact public UL.
- Stable episode IDs across real unpublish/republication events; tests cover Catalog behavior for recurrence of the same ID, not a live lifecycle.
- Whether no-deadline rows on other works are free. They remain unknown until the exact variant is positively established.
- Other reader layouts, transformed/composed draws, and capture inputs lacking currentSrc-to-Blob-to-canvas identity or exact pixels.

## P1 Discovery implementation (2026-10-12)

- Added a Kadocomi-only Discovery adapter and CLI Discovery-registry entry; viewer Crawl registry, Batch registry, Core Runner, Catalog schema, and other adapters are unchanged.
- It accepts only the verified HTTPS work route and observed query shapes, opens the unique public episode list, clicks the unique exact expansion control, and waits at most 12 seconds for two identical scoped snapshots 500 ms apart with episode-row count equal to the declared total. It allows only zero or one exact known ended-publication placeholder (`その他の話は公開終了しました`) with one paragraph, no attributes, links, or episode title. The marker text, index, and adjacent episode labels participate in settlement stability; unknown or duplicate non-episode children fail closed. It does not count page-wide recommendations or teaser links.
- Every row is validated and buffered before yielding. Wrong-work IDs, duplicate IDs, ambiguous rows, access-gate text, malformed deadline text, a missing title node, a changed heading/title, or an incomplete count fails closed. A clean list is emitted newest-first.
- Source external IDs are work_id:episode_id; saved episode locators are canonical query-free URLs. order_label comes only from the observed EpisodeThumbnail_title__ node. No numeric position is inferred.
- Future explicit row deadlines classify free and set free_until; a later observed NULL clears stale expiry. A no-deadline row classifies free only on KC_004915_S; other no-deadline rows and expired deadlines remain unknown. Current observed public rows are available=true.
- Full may mark absent Sources unavailable only after the entire declared list is validated. Incomplete full runs yield no records and do not reconcile missing Sources. Incremental leaves unobserved Sources untouched. Existing Source/Item IDs, Completed status/timestamp, CrawlRuns, and Artifacts survive disappearance/reappearance with the same external ID.
- allow_inferred_display_positions=False is set on the Kadocomi adapter. Existing display positions are preserved; new Sources have NULL positions. No global hints are emitted.
- The shared service initializes Work.title from WatchlistTarget.label and does not consume DiscoveredItem.canonical_title; the adapter reports the validated canonical name from work-page og:title but does not rewrite Work metadata. Use the actual Work name as the dedicated Watchlist label.

## P1 validation (2026-10-12)

- Added strict parser/access unit coverage, CLI registry coverage, and browser-backed local synthetic-listing tests. The integration fixture exercises `[1,2,3] -> [2,4] -> [1,2,3,4]`, deadline-to-NULL refresh, an ended-publication placeholder, rejection of an unknown non-episode child, a completed source disappearing and returning with its Source/Item/Completed/CrawlRun/Artifact identities intact, position preservation, incomplete-full no-reconciliation, and incremental unseen-source behavior.
- Focused command passed: `tests/unit/test_kadocomi_discovery.py tests/integration/test_kadocomi_discovery_browser.py tests/unit/test_cli.py::test_discovery_and_batch_registries_contain_supported_sites` -> 18 passed / 0 skipped after the sibling-title containment guard and malformed-row regression case. Ruff passed on changed Python files.
- The affected shared Discovery/Catalog/CLI plus Kadocomi command reported 205 passed, 1 failed, 734 warnings. The only failure was `test_younganimal_crawl_registry_uses_configured_work_entry_before_navigation`; the root reproduced it against the pre-Kadocomi CLI baseline (`ceb3434`), confirming it is not a Kadocomi regression. No unrelated fix was made.
- Independent Reviewer initially reported 67 passed / 0 skipped. Its final review verified the exact title, ended-placeholder classification, restored title-within-anchor guard, and completed-source disappearance/revival fixture. The final changed browser cases independently passed 2 / 0 skipped. Final P1 gate: PASS, BLOCKING=0. Lead accepts P1 and advances to P2.
- Bounded live full command, using only the isolated `work/kadocomi/p1-live-20261012/` Watchlist and Catalog through shared Crawler Chrome CDP, completed with 53 observed, 53 new, complete=true. The subsequent incremental command returned 5 observed, 0 new, known-streak stop. Catalog audit confirmed 53 unique work-scoped external IDs, all available=true, all display positions NULL, 46 explicit future deadlines, 7 NULL deadlines, and 53 canonical query-free episode targets. The Watchlist label remains Work.title. No viewer was opened during P1 live verification.
- Live checks exercised the canonical no-query work URL and the observed `?episodeType=first` variant; both returned HTTP 200, redirected to/add `episodeType=first`, and exposed identical `og:title` and document title. The exact title suffix includes U+30A6 (`ウ`) before U+30A9 (`ォ`); an earlier fixture/validator omitted that character and failed closed. The validator and fixtures now match the observed public title.

## P1.5 shared position-inference hook (2026-10-12)

- `DiscoveryAdapter.allow_inferred_display_positions` defaults to `True`, so
  existing adapters retain their current behavior.
- Setting it to `False` suppresses only position fallback inference when
  complete global hints are absent: full, exhausted incremental, and
  early-stopped incremental runs leave existing positions unchanged and new
  Sources NULL. Complete validated global hints still apply.
- Incomplete runs still do not finalize positions. The hook does not change
  Catalog schema, missing-source reconciliation, item status, Completed state,
  or Artifact identity.
- Changed scope: shared `DiscoveryAdapter`/`DiscoveryService`, focused unit
  coverage, `docs/DISCOVERY_AND_BATCH.md`, this note, and `note/00_core.md`.
  No Kadocomi Discovery parser or live-site behavior changed in this iteration.
- Root-reported pre-change baseline: `tests/unit/test_discovery.py` — 46 passed,
  0 skipped (9.03s). This is the prior baseline, not validation of this diff.
- Current validation: `tests/unit/test_discovery.py` — 51 passed, 0 skipped
  (10.88s); Ruff on `base.py`, `service.py`, and `test_discovery.py` — passed.
- No live-site work was performed in this iteration. Independent Reviewer
  verified the exact final diff: BLOCKING=0, outstanding NON-BLOCKING=0,
  independent targeted validation 51 passed / 0 skipped, diff check clean.
  Lead accepts this shared-hook checkpoint and advances to P1 implementation.
  Site-local history/republication fixtures remain required for the P1 gate.

## P2 capture implementation and live status (2026-10-12)

- Added a Kadocomi-only direct adapter and bounded native capture observer. Initialization validates the exact listed episode and current free deadline before entering its canonical episode URL, then verifies work/episode metadata and reader identity. No shared Core, Batch, policy, or CLI behavior changed.
- Capture accepts only the observed reader shape: one first-page canvas wrapper, two wrappers per following content slide in physical right-to-left order, the paired main-reader END markers at one boundary, and at most one trailing non-content slide. Each wrapper must have the observed `_pageCanvasWrapper_` class prefix and `data-type="contents"`, with exactly one owned `_root_bx4cr_` canvas. It captures only those wrapper-owned canvas slots before END and never enters the trailing recommendation.
- Every output WebP is the original retained Blob byte sequence. Before returning it, the adapter checks draw-time `currentSrc` to Blob identity, full-frame source/destination geometry, identity transform, safe draw state, bounded size/pixels, decoded RGBA equality with the canvas, and unchanged source/canvas/layout after asynchronous reads. Blob references are released after successful consumption. Locator and screenshot fallbacks fail hard.
- P2-specific changed paths: `src/screenshot_crawler/site_adapters/kadocomi/adapter.py`, `native_capture.py`, package exports and site README; `tests/unit/test_kadocomi_native_capture.py`; `tests/integration/test_kadocomi_adapter_browser.py`; and `note/12_kadocomi.md`.
- Before the final readiness adjustment, the four-file focused command passed 32 / 0 skipped. After the adjustment, combined `tests/integration/test_kadocomi_adapter_browser.py tests/unit/test_kadocomi_native_capture.py` passed 16 / 0 skipped, including both computed-direction fixtures, exact wrapper DOM, trailing-marker exclusion, and missing-main-END timeout behavior. Ruff passed for Kadocomi production files and focused tests; `git diff --check` passed. These are the post-adjustment focused results.
- The latest implementation accepts computed CSS direction `ltr` (prior P0 inspection) or `rtl` (new 1920x1080 shared-CDP context) only with `splide--rtl` and physical right-to-left slot geometry. Root readiness without content slots or an END marker waits only within the bounded initialization timeout and never authorizes capture.
- The first P2 production Runner attempt used canonical query-free episode `KC_004915_S:KC_0049150000400011_E`, direct strategy, a fresh anonymous Context from shared Crawler Chrome/CDP, and 1920x1080@1 viewport. It failed closed because the implementation's incorrect `canvas[data-type="contents"]` selector returned no slots; it did not prove that site content was unavailable. Independent Tester DOM diagnostics established the correct wrapper/canvas and paired END-marker shapes above. The owned page/context were closed and remote Chrome remained running. Artifacts are isolated under ignored `work/kadocomi/p2-live-20261012/` and are not committed.
- The corrected production Runner passed live verification on 2026-10-12 from a fresh anonymous context connected through shared Crawler Chrome/CDP. It measured a 1920x1080 viewport, started from the canonical query-free episode 4.1 route, and retained the exact `KC_004915_S:KC_0049150000400011_E` identity through END. The Runner returned `stop_state=end` with 21 captures: one initial slot followed by ten two-canvas spreads. Every captured source slot passed currentSrc-to-retained-Blob provenance, full-frame draw, decoded-pixel equality, and stable-layout checks; every output was byte-preserved `.webp` / `image/webp`, RIFF/WEBP magic, 836x1200. No screenshot or re-encoding path was used.
- The final live snapshot had 13 slides and 21 content slots; the explicit main END was at slide index 11 with the paired `data-n=1,2` markers, while the trailing recommendation marker was at index 12 and was not captured. The observed main reader retained `splide--rtl`, physical right-to-left slot order, and computed `rtl`; the capture hooks were installed and there was no content outside the reader slides. The fresh context observed only HTTP 200/204 responses. Owned context was closed and shared Chrome remained running. Lead independently opened all 21 isolated output artifacts with Pillow and confirmed valid WebP files at 836x1200; this checks artifact metadata, not source-pixel provenance. Sanitized audit is in ignored `work/kadocomi/p2-live-20261012/attempt4/result.json`.
- Independent Tester used a separate normal-renderer Blob/draw hook to audit all 21 live page files. Each saved byte sequence matched its corresponding WebP Blob exactly; all 21 decoded to 836x1200, full-frame identity draws with zero RGBA mismatch against the actual canvas. Physical slot x-coordinates descended in right-to-left order; 11 ordinary one-slide advances, including the final advance to END, reached explicit END without changing episode identity. This is an independent viewer-source-to-page-file audit, not a ZIP audit and not a claim about opaque original network responses.
- P2 focused local tests passed 16 / 0 skipped, with Ruff and `git diff --check` passing. Independent Reviewer reran 16 tests / 0 skipped and verified the corrected production diff, final live evidence, and current site notes: final P2 PASS, BLOCKING=0. Lead accepts P2 and advances to P3. Independent Tester also found a different first-episode layout (38 content canvases over 21 slides) whose order/END pattern is not covered; it remains unsupported and is not generalized from the 4.1 evidence. P4 independent ZIP/source audit is still required.

## P3 policy and local Batch/ZIP integration (2026-10-12)

- Added `KadocomiSitePolicy` and registered it with the manual Crawl adapter, Batch adapter, and Batch Policy registries. Direct is the only accepted strategy; named quota and grant-only resources remain unsupported.
- A candidate requires `site=kadocomi`, `available=true`, `access_mode=free`, a well-formed work-scoped `work_id:episode_id`, and either a NULL deadline or an aware future `free_until`. Expired/equal, malformed, or naive deadlines and non-free modes are ineligible. In Batch, the adapter binds the canonical query-free Catalog target to the configured external identity and rechecks current list membership/free state/deadline before episode entry.
- Manual Crawl accepts explicit `--access-strategy direct`; its default `auto` is rejected by the adapter. Batch uses the existing plan/run CLI and shared executor/runner/packager. Display position remains NULL; no title/order-derived numeric prefix, archive renumbering, or Catalog/Core/Batch changes were introduced.
- Local browser integration now exercises Discovery → Catalog → Planner → Executor → CrawlerRunner → native WebP manifest pages → ZIP → Artifact/Completed. The nominal run packages three fixture source bytes unchanged, confirms canonical source and Catalog metadata precedence, and uses only the explicit END stop. Fresh-runtime expired row, foreign episode redirect, and missing END each fail with Item still pending and no Artifact/ZIP.
- Targeted P3 command passed: Kadocomi policy, CLI registries, canonical-target guard, nominal Batch flow, and runtime-failure cases → 27 passed / 0 skipped (5 asyncio deprecation warnings).
- Affected regression command passed across Batch, Executor, naming, Catalog, packaging, and the existing site-policy suite → 301 passed / 0 skipped (469 asyncio deprecation warnings, 34.28s). No real site was used for P3; local browser-backed fixtures were used. Independent Reviewer verified the final material diff and current notes, with 25 focused passes (13 deselected, 0 skipped) plus 29 CLI/packaging passes (0 skipped): P3 PASS, BLOCKING=0, NONBLOCKING=0. Lead accepts P3 and advances to P4. The shared-CDP CLI Batch and independent ZIP/completion audit remain required; Root's final full suite is running.

## Checkpoint template (phase完了時に追記)

```text
Phase:
Branch / commit / date:
Scope and evidence:
  OBSERVED:
  INFERRED:
  UNKNOWN / NOT VERIFIED:
Changed paths:
Test results (commands, PASS/FAIL/SKIP):
Live browser / source image audit:
Reviewer findings (BLOCKING/NON-BLOCKING/VERIFIED):
Decisions and tradeoffs:
Remaining risks / next step:
```

Local実サイト証拠は`work/kadocomi/`等の隔離・gitignored領域へ。
cookie、session token、署名付きURL、実画像そのもの、機密metadataはcommitしない。
