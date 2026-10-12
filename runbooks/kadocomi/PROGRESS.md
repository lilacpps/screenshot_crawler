# Kadocomi Free-Only Adapter - Progress / evidence ledger

Status: P1 Discovery PASS after independent review (BLOCKING=0) and bounded live validation.
P0 listing/access contract and P2 capture evidence/design gates passed review. P2
capture implementation, P3 Batch/ZIP, and P4 independent E2E have not started.
Unverified behavior is not recorded as success.

## Stage checkpoints

| Stage | Status | Evidence / remaining work |
| --- | --- | --- |
| P0 Site and source research | CONTRACT PASS | Exact 53 episode rows plus one explicit ended-publication marker in the public UL; anonymous work/episode identity; target-scoped no-deadline proof; source-to-draw WebP proof; reader END observed. Exact historical episode set remains unknown. |
| P1 Discovery | PASS | Strict scoped list parser, exact known ended-publication placeholder handling, history-safe full/incremental behavior, 18 focused passes, isolated live full/incremental validation, independent Reviewer BLOCKING=0. |
| P1.5 Position safety | PASS | Shared opt-out hook committed as ceb3434; independent Reviewer BLOCKING=0; 51 passed / 0 skipped. Kadocomi opts out and its persistence behavior is covered in P1 integration. |
| P2 Viewer/Capture | EVIDENCE AND DESIGN PASS; IMPLEMENTATION NOT STARTED | Normal-renderer source Blob mapping and five exact pixel comparisons, 21 source slots, 11 content slides, explicit END marker. Implement guarded source-native capture after P1 review. |
| P3 Free-only Batch / ZIP | NOT STARTED | Add site policy and validate direct-only planning, execution, artifact/ZIP behavior after P2. |
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
- Reader navigation through ordinary LEFToverlay clicks traversed 21 content slots over 11 right-to-left content slides while remaining on the exact episode. The next slide (12 of 13) had no content and exposed two div._endOfBookWrapper[data-type=end-of-book] markers. A separate PR element was excluded. No copyrighted pixels or source bytes were retained in repository evidence.

## P0 INFERRED, LIMITED

- Public-list membership plus official free-WEB service and a positive anonymous exact episode supports the observed public WEB row variant. Explicit future deadlines classify free; no-deadline rows classify free only for the independently verified work KC_004915_S. Other no-deadline works and expired-deadline rows remain unknown.
- Source positions must not be inferred from compact visible rank or episode IDs. Existing positions remain unchanged and new positions remain NULL until a site-wide order authority is proven.
- The retained Blob source gives a non-screenshot, source-native capture path for the observed renderer. P2 code still needs per-capture provenance, pixel equality, page identity/order, and safe END handling.

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
