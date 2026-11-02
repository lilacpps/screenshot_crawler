# Watchlist URL Registration — Progress

> Status: Stage 01-06 COMPLETE, including the seven-site title follow-up (2026-11-03). Current targeted344 pass; affected1020 pass with one Windows path-length failure passing on short-path rerun. Earlier full-suite evidence is distinguished below. Stage 07 not started.
> Stage 01–05に続きStage 06を承認済み。Stage 07は対象外。
> Runbook: [README.md](README.md)

| Stage | Status | Exit evidence / next action |
|---|---|---|
| 00 Current contract audit | COMPLETE (static audit) | [設計・証拠](00-contract/RESEARCH.md): 11site URL/title/変換matrix、Resolver hook、Work draft/atomic save/Full境界、Kadocomi pilotとStage 01ファイル/testを確定。Liveは全site未検証 |
| 01 URL resolver + pilot | COMPLETE (`b94b7b9`) | 168 new + 653 affected passed; independent review PASS |
| 02 Registration draft + naming | COMPLETE (`43b096a`) | 256 related passed; Reviewer PASS after corrections |
| 03 Batch registration GUI | COMPLETE (`a9beb15`) | 97 GUI/adjacent integration passed; native layout capture; Reviewer PASS |
| 04 Scope editor draft integration | COMPLETE (`a7ec838`) | 181 related Unit/GUI/browser passed; independent review + follow-up PASS |
| 05 Atomic save and E2E | COMPLETE (this checkpoint) | Atomic/CAS/ownership/E2E and independent review PASS; full 6524 passed / 3 unrelated timing failures / 0 skipped |
| 06 Site URL/metadata coverage | COMPLETE (follow-up checkpoint) | 11site title hooks、追加7site live20、targeted344 pass、独立review PASS。詳細・affectedの環境制限は末尾参照 |
| 07 Listing preview coverage | NOT STARTED | 既存4サイト先行、残り7サイトを別Stageで段階拡張 |

## Stage 00 checkpoint — 2026-11-02 JST

- Branch `main`; HEAD `faa4677a3f20e0f0b818c81857e33866a5ab1af5`。
- 開始時差分: `crawler.yaml`, `watchlist.yaml` modified、`.None.job.lock`, `.catalog.sqlite.job.lock`, `.watchlist.yaml.job.lock`, `debug.log` untracked。既存差分を保持し、運用データ/lock/profileへ操作なし。
- 成果物: `00-contract/RESEARCH.md`、`00-contract/README.md`、本ファイルのみ変更。current-state noteは現行仕様/動作変更がない監査のため更新不要。実装Stageで共通/site noteを同期する。
- 照合: AGENTS.md順のauthority、GUI_README、関連notes、11site Discovery parser/metadata/preview実装と既存Unit/Integration期待値、WatchlistService/WorkDraft/WorkEditor/MainWindowの保存→Full signal。
- 設計: 共通Resolverにsite URL/selector分岐を置かずDiscoveryAdapterの任意hookから既存parserを再利用。URL-only判定とPage metadata/完全一覧取得を分離。pilotはKadocomi episode→work（既存prefix/query検証、readerを開かない）。命名は人の確定、異site groupingも明示操作。複数Workのmember patchを1proposalへ合成し、CAS/Catalog snapshot/TTL検証後に1回のapply_edit。
- 発見: PiccomaのWatchlist起点はviewer URLで一覧URLではない。一部parserの入力検証は新入口の安全基準より緩い。Full inventoryとGUI完全一覧previewは別で、後者はMagapoke/Jump+/Zeblack/Comic DAYSのみ。ほか7siteの複数key詳細設定はblockedを継続。Zeblackの現titleはlabel由来で新登録の一次根拠に使えない。
- 検証: 静的読取と文書差分/リンク確認のみ。pytest/ruff/Integration/Research/full suite未実行（code/test変更なし）。実行0・skip 0（runなし）。漫画サイトのLive/CDP未実施。辞書候補の公式公開ドキュメントだけ参照し依存は追加していない。
- 次Stage: Stage 01の設計上の開始条件は成立、阻害BLOCKERなし。ただし今回は開始しない。実装時はfeature branch/差分を再確認し、11site入口検証とKadocomi限定pilotのtargeted/affected/local browser testsを実行する。実サイト未確認を成功扱いせず、7site preview・metadata非消費経路・辞書採用の未解決境界を後続へ引き継ぐ。

## Change discipline

- 各Stage開始時に現在のHEAD、作業branch、未commit変更、他作業とのmain_window.py競合を確認。
- Stage 00はread-only監査を原則とし、成果物は本RunbookとPROGRESSの証拠更新のみ。production codeを書かず次Stageへ自動進行しない。
- 各Stage終了時に、証拠（読み取った関数/関連テスト/fixture/現行site挙動）、判定した仮定、未解決・BLOCKER、次Stageに進んでよい根拠を追記。
- 旧Stageの結果を未検証で COMPLETE にしない。サイト実観測なしなら「未検証」と記す。
- 通常運用のwatchlist.yaml、catalog.sqlite、Books/ZIP、Cookie、quotaデータは変更しない。検証は隔離された一時データのみ。

## 2026-11-02 Stage 00後の確定判断

- [DECISIONS.md](DECISIONS.md): 現行Discovery用の安全な正規URLが確定するなら、作品ID/title未取得でもunknownのままlabel/Work/keyを手動確認して登録可能。URL不正・起点不明は手動確認でもブロック。保存直前の所有競合・Catalog/Watchlist照合は必須。
- 初期のread-only完全一覧preview対応はmagapoke/jumpplus/zeblack/comicdaysの4サイトだけ。7サイトの詳細設定が必要なWorkは理由付きblockedとし、後続Stage 07でサイト単位に拡張。
- Stage 01の対象は11サイトの厳格な正規URL判定、Kadocomi episode→work pilot、identity/title unknown状態の表現。手動確認と一括保存はStage 02–05。Stage 06はサイト別URL変換/metadata、Stage 07は完全一覧preview拡張。
- Stage 00の監査時点記録を改変しない。今回の更新はRunbook文書のみで、コード・テスト・運用Watchlist/Catalog/ZIP/Chromeは変更していない。

## Stage 01 checkpoint — 2026-11-02 JST

- Base: latest fetched origin/main `82e9f92`; feature/watchlist-url-registration.
  User config/Watchlist/locks/log changes preserved, not used as test data.
- Implemented immutable URL evidence, bounded pure resolver, all 11 site-owned
  canonical entry hooks, Kadocomi same-work episode-to-detail conversion and
  optional detail-only og:title observation. Native work identity stays unknown
  for episode-only Comic DAYS/Jump+/Hanayume; title unknown unless observed.
- All unsafe/unsupported URL forms stay blocked. Percent escapes are conservatively
  unsupported. Kadocomi natural document response uses Playwright route.fetch
  with max_redirects=0 to reject Location before Chromium follows it; all other
  requests are blocked. No general HTTP client, reader or acquisition action.
- Tests: 168 new Unit/artificial-browser passed; 653 affected Discovery/listing/
  Kadocomi browser passed; zero skips. Ruff src/tests and diff check passed.
  Independent Reviewer: PASS, zero blockers. Full/Research not run at this stage
  (bounded change); Live resolver not verified. HTTP-200 authentication/content
  ambiguity remains a metadata expansion concern for Stage 06, never save proof.
- Docs and core/all 11 site notes synchronized. No CLI/GUI/schema or data mutation.
  Next Stage 02 permitted by tests and review.

## Stage 02 checkpoint — 2026-11-02 JST

- Added Qt-free BatchRegistrationDraft, explicit Work grouping/selection,
  same-site proven identity folding, readable naming and manual confirmation.
  Work/key collisions never merge groups; existing IDs and target dataclasses
  (scope/order/segments/enabled included) are preserved.
- Retry/manual edits preserve edited values but clear all confirmation evidence;
  automatic keys follow Work/site changes while manual keys do not. Same-site
  unknown ownership blocks; unsupported existing Source URLs require consistent
  existing key+native Work proof or remain unresolved. No Catalog writes.
- pykakasi 2.3.0 installed/tested on Windows Python 3.14; GUI extra >=2.3,<3.
  GPL3+ and bundled dictionary location/API sources documented in core note.
  ASCII titles do not require provider; absent provider leaves manual entry.
- 256 draft/resolver/Watchlist/WorkDraft tests passed, zero skipped. Ruff and diff
  check passed. Independent review initially found confirmation invalidation
  and unresolved-owner blockers; corrected and re-reviewed PASS, zero blockers.
- No browser changes, so no new Integration/Live/Research/full run in this Stage.
  Docs/note synchronized. Stage 03 may proceed; no persistence/UI yet.

## Stage 03 checkpoint — 2026-11-02 JST

- Added MainWindow URL registration entry and dedicated modal draft dialog:
  bounded background resolution, optional detail metadata, canonical/evidence and
  readiness display, manual label/reading/key edits, explicit grouping/existing
  Work selection, Work-level check selection and per-row retry. No persistence.
- Row switching/retry/grouping preserve other edits. Dirty close has Discard/Cancel;
  new corrected URLs require reanalysis; blocked URL has no confirmation bypass.
  Dedicated worker Pages use shared CDP lifecycle only. CDP failure leaves safe
  URLs eligible for manual confirmation; stale-generation rows are ignored.
- MainWindow retains Inventory execution checks and blocks conflicting job/edit/
  path operations. Active/unverified jobs disable registration. Save/detail/preview
  remain disabled until later Stages.
- 97 GUI + WorkEditor/Watchlist + discovery-toggle/execution-input Integration
  passed, zero skipped; ruff/diff checks passed. Independent Reviewer PASS.
  Its minor metadata factory-exception concern was also contained per row.
- Layout: native Windows Qt capture `.tmp/watchlist-registration/stage03-native.png`
  at 980x800 verified Japanese labels/form/table/actions; larger/smaller Qt
  captures and 100-row scrolling tested. Offscreen rendering lacked fonts and is
  not visual proof. Computer-use inventory found no targetable hidden test window,
  so no user operational window was controlled; Qt native capture is the evidence.
- Docs/GUI_README and note/00_core synchronized. No live manga-site requests,
  Research or full suite this Stage (UI/local integration only). Stage 04 allowed.

## Stage 04 checkpoint — 2026-11-02 JST

- Extracted original Work snapshot validator and Catalog snapshot identity into
  Qt-free helpers with compatibility GUI wrappers. Normal WorkEditor save/full
  contract retained; draft-only child clones WorkDraft, disables add/switch/reload,
  requires explicit scope confirmation for every key and returns validated DTOs.
- Immutable Work proof includes member patch, revision, Work version, Catalog
  identity, listing digest/timestamp and confirmed keys. Parent checks identities,
  membership/ownership and patches only this Work. Cancel/edits/stale listing or
  changed baseline cannot overwrite other Work drafts or write persisted data.
- Existing scope/order/segments/enabled load unchanged. Added regression exposed
  inherited segment normalization tightening an unchanged open scope on preview;
  corrected only draft-only mode to preserve exact prior scope when selected rows
  are equal. Explicit edits still apply. New ordered keys use WorkDraft.add.
- 181 targeted/affected Unit/GUI + four-site listing browser tests passed, zero
  skips. Ruff/diff check passed. Independent Reviewer PASS, then material scope
  fix re-reviewed PASS, zero blockers. Reviewer's separate pytest was prevented
  by its TEMP permissions; root's short isolated basetemp runs supply test evidence.
- Docs/DISCOVERY_AND_BATCH, GUI_README and note/00_core synchronized. No site
  adapter/live behavior changed; no new Live/Research/full run at this gate.
  Stage 05 authorized and ready; bulk persistence is completed in the checkpoint below.

## Stage 05 checkpoint — 2026-11-03 JST

- Added Qt-free RegistrationService: selected Work composition, final summary,
  fresh Watchlist/Catalog/ownership/URL/complete-list proof validation under
  CatalogJobLock, then one apply_edit with revision CAS. Conflict/stale proof
  rejects the whole selection. Existing stable fields and unrelated targets,
  Source owners, Catalog, ZIP and history are preserved.
- Added background GUI preview/save, actual final-preview modal, verified
  readback, retained unselected drafts/reopen, explicit committed-but-unverified
  freeze, Catalog refresh without losing manual values, and existing Full
  confirmation once. Full No reports saved/not run/unsynchronized; Yes/failure
  use the existing independent job. No automatic Batch/scope-sync/renumber.
- Fixed ownership lookup to use real SourceTarget web locators, with real Catalog
  regression fixtures. Display ownership indexes are bound to the immutable
  Catalog snapshot and candidate signature; final save always rereads under lock.
  Partial-save candidate IDs are monotonic to avoid overwriting retained rows.
- Kadocomi route.fetch errors are contained inside the callback and sanitized;
  only one exact main-frame document GET is permitted. Local redirect/fetch-error
  tests pass. Bounded live retry observed unique detail title「夫婦以上、恋人未満。」
  at 2026-11-02 23:48 JST for KC_004915_S after same-prefix episode conversion.
  Dedicated shared-CDP Page closed; no reader/resource/Capture or persisted data
  action. Other ten sites' registration metadata remains live-unverified.
- Windows native GUI synthetic E2E covered MainWindow entry, pasted candidates,
  explicit cross-site Work assignment, per-key detail/range/segment confirmation,
  ready rows, final preview, atomic save, Full No and reloaded inventory.
  Catalog bytes unchanged, Full question exactly once, unselected row retained.
  Artifacts (ignored): `.tmp/watchlist-registration/stage05-{main,candidates,detail,
  ready,final-preview,full-confirm,main-saved}-native.png`,
  `stage05-native-result.json`. Native Japanese text/control layout was inspected;
  offscreen missing-font rendering is not used as visual proof.
- Tests: 439 affected Unit/GUI/local-browser passed (zero skips); later material
  changes additionally passed GUI 20, observer/resolver 169, cache-related 88,
  and service/draft 36 tests. These runs overlap and are not an additive total.
  Independent Reviewer passed the production diff and all material follow-ups,
  separately running 95 related tests, then 10 observer and 45 service/draft/detail
  tests. Zero remaining BLOCKING findings. Docs synchronization independently
  reviewed as consistent. Final ruff src/tests and git diff --check passed.
- Full suite uses an isolated Git snapshot with current src/tests/pyproject
  overlaid and tracked default YAML, never the user's operational YAML. First
  attempt stalled in an existing ComicFUZ asyncio fixture teardown and was
  terminated after stack diagnosis (not a passing full run). Final 6527-test
  rerun completed with per-test/fixture timeout 180s and verbose evidence:
  **6524 passed, 3 failed, 0 skipped, 6737 warnings, 3216.34s (53:36)**.
  No test was deselected; source/test hashes match the final working code.
  New registration Unit (204), GUI (20), observer Integration (10) all passed.
  Full is not all-green; the three unrelated timing failures are retained below.
  Command (from the isolated snapshot, PYTHONPATH set to that snapshot):
  `python -m pytest -vv -q -p no:cacheprovider --timeout=180 --timeout-method=thread -o faulthandler_timeout=120 --basetemp=<isolated TEMP>`.
  pytest-timeout 2.4.0 is only a local verification tool, not a new application
  dependency/configuration. Log: `.tmp/watchlist-registration/stage05-full-final.log`.
- Full failure isolation:
  `test_comicfuz_runner_crawls_verified_spreads_to_positive_end` timed out waiting
  for stable page-turn completion (PageChangeTimeoutError, one page saved).
  The same test passed alone on final code (3.95s) and isolated origin/main
  (4.34s). Its test/Adapter/Runner files are unchanged from main; no unrelated
  capture behavior was modified to conceal this failure. Independent Reviewer
  confirmed the unrelated timing instability is not a Stage 05 blocker. Isolated
  diagnostics are under TEMP/wur_full05final/test_comicfuz_runner_crawls_ve0.
  Younganimal
  `test_younganimal_initial_native_redraw_is_bounded_and_keeps_proofs[mapping_drift]`;
  final code alone passed (1.68s), isolated origin/main alone passed (1.98s),
  and its test/Adapter/Runner are unchanged. It failed closed before redraw began;
  the subsequent fixture assertion subscripted a None redraw diagnostic.
  BookWalker
  `test_bookwalker_initial_page_rejects_counter_ahead_of_pixels_and_ignored_home`
  uses a fake Page with 120ms deadline: it raised the expected fail-closed error,
  but only one Home fit before the deadline (expected two). Final code alone
  passed (0.47s), isolated origin/main alone passed (0.68s). Its test/Adapter/
  Runner are unchanged. Independent Reviewer confirmed all three paths are
  outside registration and do not block Stage 05; no guard/fixture was weakened.
  Test timing stabilization remains a separate maintenance limitation.
- Final-code follow-ups: service/draft/detail 45 passed (3.97s), GUI 20 passed
  (6.03s), native GUI E2E repeated successfully, ruff and diff check passed.
- Research/probe suite was not separately expanded (no PoC changes). New site
  URL conversion and seven-site complete-list capability remain out of scope.

## Stage 05 usability follow-up — 2026-11-03 JST

- Added existing-Work search above the membership combo: partial matching across
  Catalog title, all saved labels/keys/sites and work_key, NFKC/casefold with
  whitespace AND terms and match/total count. Current/pending selection is kept
  visible; filtering does not change membership, confirmation, dirty state or
  preview. Search text survives row changes; grouping remains explicit.
- Added the visible reason/action table column and moved readiness explanations
  to the first lines of selected-row evidence. Work-key collision, invalid URL,
  missing confirmation and unsupported/stale detail reasons use the existing
  readiness authority without weakening validation.
- Final preview starts with add/update/unchanged counts and readable YAML
  excerpts: additions, existing entries before and after changes. Field names,
  order and optional scope/order/segments use the existing writer serializer via
  read-only format_targets_yaml. Dataclass repr removed from settings display.
  The excerpt explicitly omits comments/unchanged content; actual save preserves
  them through the unchanged writer/CAS/atomic path.
- Major files: gui/url_registration.py, registration/service.py,
  watchlist/service.py, existing GUI/service tests. docs/GUI_README,
  docs/DISCOVERY_AND_BATCH and note/00_core synchronized. No site behavior or
  operational YAML/Catalog/ZIP/history changes.
- Targeted GUI first 27 passed; final GUI/service/normal WorkEditor/Watchlist/
  WorkDraft affected selection **182 passed, 0 skipped** (37.34s). Independent
  Reviewer: **PASS / zero BLOCKING**, separately 46 GUI/service tests passed.
  Ruff src/tests and git diff --check passed. Full/Research/live and additional
  browser-backed Integration were not repeated: presentation plus read-only
  serialization only, no writer/network/capture branch changes. Qt GUI integration
  and isolated native Windows visual QA were performed.
- Native screenshots at 1200x940 and 980x800: visible search/count/reasons,
  filtered dropdown and YAML-first preview. Isolated report confirms 2/3 matches,
  work_key collision explanation, YAML shown, and unchanged Watchlist/Catalog.
  Artifacts: `.tmp/watchlist-registration/search-reasons-{980,1200}-native.png`,
  `search-results-native.png`, `search-preview-yaml-native.png`,
  `search-preview-native-result.json`. No network or real data used.

## Stage 06A checkpoint — 2026-11-03 JST

- New Stage 06 request supersedes the earlier stop-at-05 instruction. Stage 07
  remains outside scope. Baseline feature branch `09c040d`; user YAML/locks/log
  unchanged and never used as test data.
- Added pure numeric Zeblack viewer→same-title chapter/list conversion. Added
  optional title observations for BookWalker, ComicFUZ, Younganimal and Piccoma.
  Small registration/observation.py permits one exact main-frame document GET,
  rejects redirects and aborts subresources/POSTs. Caller owns shared CDP Page.
  Canonical and site-local native/title/episode-binding proofs precede title use.
  Existing Kadocomi, Discovery/Batch/capture and complete-list preview unchanged.
- Bounded investigation: Zeblack 3957 static list/detail had generic title only;
  Manga ONE /manga/2379 returned 404; Magapoke /title/00695 returned 302, not
  followed. Hanayume series work document exposes title but work→seed proof is
  not yet implemented. No reader/episode was opened, no resource/POST/API action.
- Production metadata live verified via dedicated shared-CDP Pages, one GET each
  at 2026-11-03 05:54 JST: BookWalker series 317089; ComicFUZ work 1970;
  Younganimal series 7103c2c1e9f08; Piccoma product 28600/episode 1910027 input,
  navigating only product listing. All four returned title; Page cleanup done.
  Evidence is sanitized metadata JSON only under `.tmp/watchlist-registration/`.
- Targeted: 209 resolver/new metadata/old Kadocomi tests passed, zero skipped;
  affected Discovery + registration drafts/detail/save/GUI: 348 passed, zero
  skipped (18.86s). Independent Reviewer PASS / zero BLOCKING, separately 199
  resolver/metadata tests. Ruff/diff check passed. Additional malformed-native
  containment case passed (1 passed, 34 deliberately deselected by targeted -k,
  no skips): direct observe also returns a sanitized manual candidate because
  the async document context catches PlaywrightError raised inside the body.
- Notes core + five affected sites and docs/GUI_README, DISCOVERY_AND_BATCH
  synchronized. Capability evidence/unsupported boundaries are recorded in
  [Stage 06 matrix](06-site-coverage/CAPABILITIES.md). At the 06A checkpoint Stage 06 was still in progress;
  work/listing→seed needs a minimal bounded proof/preview/save contract (06B).

## Original Stage 06 / 07 handoff (historical; Stage 06 completed below)

- Stage 06: add site-specific URL forms/metadata only after non-consuming evidence;
  six sites still have no automatic title observation. Percent-escaped URLs remain
  conservatively blocked. HTTP-200 login/content ambiguity needs further bounded
  metadata research; title text never becomes native identity or save proof.
- Stage 07: add complete-list read-only preview for bookwalker/comicfuz/hanayume/
  kadocomi/mangaone/piccoma/younganimal individually. Until then, new single-key
  safe/manual registration works, but multi-key/existing-Work additions needing
  detail block with a reason. No cross-site automatic Work merge is introduced.
- Original handoff excluded Stage 06/07 implementation. The new request now
  authorizes Stage 06; no Stage 07, main merge or operational data modification.

## Stage 06B checkpoint — 2026-11-03 JST

- Implements the separately reviewed [conversion contract](06-site-coverage/PROOF_CONTRACT.md).
  Piccoma product/episodes input stays blocked with only a safe observation URL
  until its optional one-document observer proves a canonical, same-product,
  oldest-first listing with exact declared count and valid unique native rows.
  The existing site access classifier selects the first unconditional-free DOM
  row; quota/rental/paid/unknown are never eligible. Existing Discovery shares
  only its unchanged row extraction/validation and retains reverse output/scope.
- Immutable in-memory input/document/seed/product/selected-ID/DOM/access/time proof
  is checked by the fresh pending parse, canonical seed parse, site validator and
  aware 0..300s age in readiness/preview/save. No network occurs under save lock.
  Retry/URL edit/blocked clear proof. Unknown title still supports human label
  confirmation after a proven URL. No proof means blocked, no manual override.
  YAML stores the canonical viewer-shaped seed; input and saved URL are explicitly
  labeled in final preview. Proof is not persisted and no schema/config is added.
- The GUI checkbox label explicitly includes safe conversion and title lookup.
  It retains the existing initially-checked metadata preference; OFF never uses
  CDP and leaves listing input blocked. Analyze uses the visible selection; there
  is no additional permission modal or reader navigation. Stage07 is unchanged.
- Production observe_conversion live check 2026-11-03 06:16 JST on product28600:
  432 same-product rows, oldest-first DOM1 free episode1910027, titleベルセルク,
  canonical seed and pure proof accepted. Dedicated shared-CDP Page closed.
  One exact listing GET, no viewer/redirect/subresource/POST/resource operation.
  Initial restricted-network attempt failed closed; authorized network retry
  succeeded. No normal Watchlist/Catalog/ZIP/history or comic data was used.
- Targeted: 313 passed, zero skipped (21.36s), proof tamper/TTL/future/naive,
  strict pending/unsafe parser, isolated YAML parity/expiry atomic save, browser
 26 count/order/foreign/duplicate/status/no-free/error/redirect cases and Piccoma
  unit regression. Affected: 140 passed, zero skipped (68.90s), GUI opt-in/error/
  edit invalidation, registration draft/detail/save, Piccoma Discovery browser,
  35 metadata and Kadocomi browser. Ruff src/tests and diff check passed.
- Independent Reviewer implementation gate PASS / no BLOCKING; separately
 64 conversion cases passed, two setup errors from its Windows temp ACL (not
  implementation failures). Root's isolated-save cases passed. Direct observer's
  inner locator PlaywrightError is sanitized by registration_document; failed
  conversion stays blocked. Native Windows Qt 980x800/1200x940 and final YAML
  modal inspected: Japanese text and controls fit, saved seed and original URL
  visible; stores unchanged. Artifacts `.tmp/watchlist-registration/stage06-*-native.png`
  and `stage06-native-result.json`, all synthetic/no network.
- All eleven capability boundaries are now audited in
  [CAPABILITIES](06-site-coverage/CAPABILITIES.md), with unsupported reasons.
  Hanayume scoped public links alone do not prove native episode/Work/order/full
  inventory; Magapoke work redirect is not followed. No guessed seed conversion.
- Isolated full verification uses `full-stage06`, git-archived tracked default
  YAML and final src/tests overlay; all 352 source/test SHA256 entries match.
  YAML matches tracked HEAD after newline normalization; operational YAML is
  never read. Initial all-in-one run timed out in pytest_asyncio's finalizer for
  unchanged ComicFUZ test_comicfuz_other_episode_route, as in earlier Stage05
  investigation. Stack/timeout recorded; no test condition/fixture was changed.
  Pytest-timeout had already ended the process before attempted own-process
  cleanup (PID was not found); shared CDP/user GUI was never targeted.
- Full collection: 6,644 nodeids. The unchanged ComicFUZ browser file rerun alone
  passed 69/69, zero skipped, 175.04s, normal teardown/exit0. The complementary
  default suite excluding only that exact file collected6,575; its later teardown timeout and continuation are recorded below.
  An isolated reporting-only plugin records collection/start/report/finish; it
  changes no fixture, result or selection. Final union and full outcomes pending.

## Stage 06 observation cleanup hardening — 2026-11-03 JST

- Extra caller-level synthetic regression reproduced an actual delayed POST
  escaping between context unroute and BrowserSession.close_page's scheduled
  Page close, even with no deliberate caller wait (normal/error 0ms cases).
  This was treated as BLOCKING and fixed, never accepted as a timing flake.
  The sentinel used an artificial local document and intercepted POST; no real
  site POST, resource action or operational data was involved.
- Small fix retains the existing restrictive Page route after observation;
  finally sets used=True, so every later request is denied until dedicated Page
  close. Caller owns/always closes the Page; no Page reuse exists in the five
  current observers. Shared context/browser routes are never touched. Normal,
  unavailable, rejected and runtime-error paths retain the restriction.
- Final targeted/affected rerun: 469 passed, zero skipped, 39 dependency warnings,
  111.48s. Includes lifecycle16, all metadata35/conversion26 browser cases,
  GUI, resolver/draft/detail/save and affected Piccoma Discovery/Kadocomi tests.
  Earlier smaller post-fix98-case run also passed. Ruff src/tests passed.
- Independent Reviewer reproduced original race, then separately ran fixed
  lifecycle16: all passed, zero skipped; BLOCKER resolved / gate PASS.
  The 16 cases cover 0/20ms timer, immediate/100ms delayed close, and all four
  success/error categories. Core and all four affected site notes synchronized.
- The broad full run used the frozen a87e16b source/test baseline; it is
  intentionally not mutated during execution. Final guard and this new test
  file are verified separately by the full affected suite above. Final reporting
  must distinguish baseline full results from post-fix validation, and must not
  claim the entire broad suite ran the final guard. Stage07 remains untouched.

## Initial Stage 06 acceptance — COMPLETE, 2026-11-03 JST (before seven-site follow-up)

- Feature checkpoints: `0943c76` (06A title observations/Zeblack conversion),
  `a87e16b` (06B Piccoma proved work-listing conversion), `7f64880` (Page-lifetime
  observation restriction). Final documentation checkpoint follows this record.
  Feature branch retained; no main merge/push or operational data modification.
- Added capabilities are precisely the [11-site matrix](06-site-coverage/CAPABILITIES.md):
  Zeblack numeric viewer→same-title list; four title observers (BookWalker,
  ComicFUZ, Younganimal, Piccoma); Piccoma product/episodes→proved first free DOM
  seed. Kadocomi's prior pilot remains. Unsupported forms are not rescued by
  human confirmation. Unknown metadata on safe canonical URLs retains explicit
  human confirmation; cross-site Work membership never auto-merges.
- Final-source live recheck 2026-11-03 07:43 JST: same four previously observed
  Works, four exact work/listing GETs, titles and pure validation accepted.
  Piccoma again proved432 same-product rows and selected1910027. Dedicated Pages
  closed; no reader, resource, Discovery, Capture, Catalog/Watchlist/ZIP/history
  action. Evidence `.tmp/watchlist-registration/stage06-final-live.json`.
- Broad verification was not a clean monolithic run. Initial ComicFUZ teardown
  timed out; the next broad run then passed1,980 calls but timed out during
  unchanged Younganimal test_episode_429's async fixture finalizer. Its body
  passed in0.08s; incomplete teardown was NOT counted as success. Final-source
  isolated rerun of that exact case passed normally:1 passed, zero skipped,
  exit0,1.84s. ComicFUZ's separate69-case run also finished normally (above).
  No fixture, timeout expectation, guard or assertion was weakened to hide this.
- Completed baseline subset:1,979 nodes with passing call AND teardown reports.
  Final source continuation selected all remaining nodes plus all469 affected
  cases using an explicit pytest @argsfile. Result: **4,702 passed, zero skipped,
  exit0,632.57s**, with6,616 existing dependency deprecation warnings.
  All469 final affected cases are included in this completed continuation,
  in addition to the earlier independent469-case rerun and Reviewer lifecycle16.
- Machine audit:1,979 baseline ∪69 ComicFUZ ∪1 isolated Younganimal ∪4,702 final
  continuation = **6,660 unique final collection nodes**, missing0/skips0,
  all with passing call+teardown witnesses.91 baseline cases were revalidated in
  the final continuation;1,888 baseline-only cases retain the frozen-source
  evidence. These counts are not added without accounting for overlap.
  The two timeout attempts remain explicitly unsuccessful executions.
  Independent Reviewer inspected the final audit/manifests/live/docs and passed
  the final evidence gate with no BLOCKER before the documentation checkpoint.
- Final source/test manifest353 files matches the current tree. Baseline→final
  differs only in registration/observation.py and the new lifecycle test file;
  all affected observers/GUI/save tests ran on final source. The entire6,660
  suite was NOT rerun in one invocation after the guard fix. Final collection
  added exactly16 lifecycle nodes and removed none. Snapshot YAML is git-archived
  tracked default data (newline-normalized equality checked), never operational
  YAML/Catalog/ZIP. Reporting-only plugin does not change test fixtures/results.
- Audit artifacts: `.tmp/watchlist-registration/stage06-final-audit.json`,
  `stage06-partition-plan.json`, baseline/final manifest JSON, collection and
  report JSONL, `stage06-full*.log`, `stage06-final-resume.log`,
  `stage06-guard-final-affected.log`. Ruff src/tests PASS; diff check PASS.
- Independent Reviewer final implementation/docs/native-GUI gate PASS, then
  original lifecycle race reproduced and fixed; independent16-case rerun PASS.
  No unresolved Stage06 BLOCKING finding remains. Windows Qt980x800/1200x940,
  candidate form/checkbox and actual-YAML preview are verified with synthetic
  stores; no visual breakage or disabled required control was observed.
- Major source files: discovery/base.py; gui/url_registration.py;
  registration/{models,resolver,observation,draft,service}.py;
  site_adapters/{bookwalker,comicfuz,piccoma,younganimal,zeblack}/discovery.py.
  Tests: unit/test_registration_{resolver,conversion}.py,
  unit/test_gui_url_registration.py and integration/test_registration_
  {metadata,conversion,page_lifecycle}_browser.py. Updated docs:
  DISCOVERY_AND_BATCH,GUI_README and this runbook's README/DECISIONS/PROGRESS,
  06 README/CAPABILITIES/PROOF_CONTRACT. Updated notes:00_core,01_bookwalker,
  06_zeblack,09_piccoma,11_younganimal,13_comicfuz.
- Limits/handoff: live evidence covers one Work per enabled observation site,
  not every Work/login/expired campaign/account state. Other six title observers
  and unproved product/share/episode transformations remain unsupported, per
  matrix; escaped URLs stay blocked. Piccoma conversion proof expires after300s.
  Stage07 is **not started**: complete-list detail remains magapoke/jumpplus/
  zeblack/comicdays only. Remaining seven sites' full-list proof/scope editor,
  and additional non-consuming URL conversion research, remain future work.

## Stage 06 seven-site title follow-up — 2026-11-03 JST

- Baseline `91309b0` on feature/watchlist-url-registration. The latest request
  explicitly expands the earlier narrow metadata scope: supplied episode HTML
  metadata may be read once without executing a viewer. The subsequent user
  instruction permits a few operational Watchlist URL/label pairs as read-only
  ground truth, without a full sweep, runtime lookup or real-data test fixture.
- Implemented title observation for Magapoke, MangaONE, ComicDAYS, Jump+ and
  Hanayume; improved Kadocomi to use exact native Work query/code/title before
  known og:title fallback. Zeblack uses the official frontend's fixed public
  title_detail GET, validating response URL/status/type/size and bounded native
  protobuf Response21 TitleDetailView1/2. It reads no chapter inventory, JS or
  viewer. Native title removes any need to strip visual list/volume suffixes.
- New pure conversions: numeric Zeblack `/title/<id>`→same-title chapter/list;
  Hanayume `/episodes/<13hex>/<positive page>`→base episode. Existing www/slash,
  Kadocomi episode/query and Zeblack viewer conversions retain their boundaries.
  Work→seed/share/short URLs are not generally supported; see the current matrix.
- All document observers now replace response CSP to prohibit inline/external
  scripts, objects, workers and form submission. Static DOM/inert JSON remains
  readable. The existing redirect/subresource/POST guard stays until Page close.
  The independent lifecycle tests explicitly inject timers with Page.evaluate,
  so this guard remains tested independently of HTML script blocking.
- ComicDAYS/Jump+ check the episode ID plus native series ID shape/title;
  Hanayume checks a unique official Work anchor. These are title evidence only,
  without independent persisted Work binding proofs: identity remains unknown
  and human assignment is mandatory. Missing metadata retains Decision A's
  explicit manual registration; observed contradictions remain blocked.
- Final CSP-enabled production observers verified all14 supplied URLs and6
  additional distinct Watchlist samples, at08:16 JST. Kadocomi's first sample
  duplicated a supplied Work and was not fetched again as an extra sample.
  All20 returned titles and passed pure save validation. Hanayume's sample
  full-width Ｓ・Ａ matches the half-width label under NFKC; existing labels are
  not edited. Kadocomi KC_005686_S intentionally retains the official full name
  「シンコンクエスト 魔王の娘は真面目勇者を堕としたい♡」.
- The same final CSP guard also passed live regression at08:20 JST on the four
  previously verified BookWalker/ComicFUZ/Younganimal/Piccoma works; Piccoma
  still selected the proven first unconditional-free seed without opening it.
  Evidence (ignored): coverage_followup_live.json and
  coverage-followup-other-four-live.json under .tmp/watchlist-registration/.
- Native Windows GUI used actual _ResolveWorker/CDP observation on one supplied
  URL per site, with isolated empty Watchlist/Catalog/runtime files. Seven
  labels auto-populated; explicit confirmation and actual saved-YAML preview
  showed all labels, canonical Zeblack/Hanayume URLs and input/saved URL labels.
  No save/Full/Capture was executed. Both isolated stores and operational YAML
  hashes were unchanged. Captures: native-seven-{analyzed,ready-1200,ready-980,
  preview}.png; result native-seven-result.json. At980x800 the list scrolls;
  form/actions remain reachable, with no broken controls or missing fonts.
- Tests: initial targeted267 passed/0skip. Final source targeted344 passed/0skip
  (all document/API observers, conversion, lifecycle16, strict resolver).
  The first CSP test iteration had6 test-only failures from evaluating a
  rejected redirect's destroyed document; the assertion now runs only for
  loaded documents, while redirect/block and single-GET assertions remain.
  Final344 passed after this correction. Ruff src/tests and diff whitespace
  checks pass.
- Wider27-file affected suite completed1020 passed/1 failed/0skip (664.48s).
  Failure: existing Hanayume Batch [already-granted-start] exceeded Windows path
  length under the long isolated basetemp, failing to create .manifest.json.tmp.
  Both parameters passed with short isolated basetemp w7h1 (2 passed/0skip).
  No packaging/access/fixture contract was weakened. Final metadata-only changes
  after the wider run began are wholly covered by the final344 checks.
  Supplementary final-source Hanayume/Kadocomi replay:85 passed/1 same long-path
  failure/0skip (310.10s); the short-path2 passed run above covers that failure.
  Replay reports include call/teardown checkpoints in
  followup-affected-remainder.jsonl. This does not replace or imply a clean
  monolithic full-suite result.
- Full pytest was not repeated for this follow-up: changes are confined to
  registration observation and site metadata hooks, with no Core/Runner,
  Catalog/Watchlist model, Discovery algorithm or save validation changes. All
  observation callers and affected site Discovery/edit/save contracts are
  covered above. Earlier full-suite evidence is historical, not a new full run.
  Live coverage is bounded to the named works/metadata, not every account,
  expired episode, special MangaONE chapter-title shape, rights or Capture flow.
- Independent reviewer: seven-site production review and final CSP/MangaONE
  title-separator/source/test/docs review PASS/no BLOCKING. Final PROGRESS
  synchronization was independently rechecked and accepted (final gate PASS).
  Short-path Hanayume rerun:2 passed/0skip.
- Notes synchronized:00_core and all11 site notes (four existing metadata sites
  also receive the shared CSP change). GUI_README, decisions, runbook/matrix
  updated. Production files: registration/observation.py and seven site-local
  discovery.py hooks; tests: resolver, Kadocomi browser fixture and two new
  metadata integration files. No stable key/owner/scope/order/segments changes,
  automatic cross-site merge or operational data write.
- Remaining: Stage07 complete-list previews for the other seven sites remain
  NOT STARTED. Independent Work/episode binding proofs and further safe
  work→seed URL forms require separate evidence. No main merge/push.
