# 00. Core 現行実装ノート

## Read-only episode-list helper CLI (2026-10-01)

`python -m screenshot_crawler.cli episode-list --url <URL>` is an operator
helper for selecting bounded Discovery endpoints manually. It recognizes only
the strict Zeblack chapter-list URL and Jump+ episode URL parsers, connects to
the shared CDP browser session, creates an in-memory `WatchlistTarget`, and
calls the matching existing Discovery adapter's `iter_records(page, target,
"full")`. It does not call `DiscoveryService.discover()`, `CatalogService`,
or `WatchlistService`, and it does not write `watchlist.yaml` or Catalog data.

Each retained record is printed in adapter order as tab-separated
`order_key`, visible `order_label`, and canonical `source.url`. A missing
`order_key` is shown as `-` so special episodes are retained. Repeatable
`--contains TEXT` applies an exact substring OR filter to the combined order
key/title display text; it is only a display filter and never chooses a
boundary. `--env-file`, `--cdp-endpoint`, and optional `--keep-open` follow the
existing CLI/CDP session contract. Unsupported URLs and adapter listing or
validation failures exit with a concise error, and the created page/session
are always closed while the remote Chrome remains running.

## Current shared Batch extension (2026-09-30)

Batch retains the generic planner/executor and existing non-Zeblack behavior.
Site Policies may opt into a small site-owned access-resource resolver. The
resolver runs under the shared AccessGuard, receives already-planned pending
candidates, returns selected source IDs plus expected local skip reasons, and
does not count its read-only site snapshot as a candidate attempt. This is an
optional extension point, not a site-name branch or YAML rule DSL.

Zeblack is the current consumer: its Work Ticket resolver reads one native
chapter/list snapshot per Work/title, matches live availability to Catalog
external IDs, and then reuses the existing grant-only Executor. Its normal
Batch phases are direct, grant-access, and one post-grant direct replan.
The generic deferred path derives the resolver resource from the planned
candidate `quota_resource`; missing or mixed deferred resources fail closed and
no site-specific resource name is interpreted by the CLI. The resolver is a
site access for `inter_candidate_delay_ms`: a previous site access is followed
by a delay before resolution, resolution is followed by a delay before the
selected grant, and a confirmed grant is followed by a delay before the
post-grant direct phase. A resolver with no selected candidate still updates
the explicit-pass pacing state, while local-only skips do not. Catalog
schema/version and the shared browser/CDP session model are unchanged.
Resolver navigation and protobuf body reads share one bounded observation
deadline, and resolver cancellation is propagated rather than swallowed.
Resolver operation and AccessGuard cleanup joins are bounded and detached
best-effort when a Playwright task does not respond to cancellation.
The generic Batch CLI reports resolver start, completion, and failure so a
deferred-resource phase remains observable while its read-only snapshot runs.
For policies that defer quota access, the CLI also partitions the unchanged
plan by `candidate.consumes_quota`: immediate candidates remain individually
visible, while deferred candidates are shown only as a pool summary with their
candidate count and policy-owned resource. The generic partition has no site
or resource-name branch, and non-deferred site output remains unchanged.

Comic DAYS is a non-deferred policy: Discovery full classifies the complete
first-party listing and is the authority for quota candidates. Its policy uses
work-scoped `work_ticket` state with `quota_limit=1`; Planner therefore passes
at most one quota candidate per work in existing Catalog order. The generic
Executor exposes an optional `SiteAdapter.configure_target_identity()` hook
before Runner navigation, allowing a site adapter to compare Catalog identity
with the target page. It also evaluates work-scoped local resource cooldown
state before opening a page for any consuming candidate. These are neutral
hooks; no site or resource name is interpreted by Core.

Comic DAYS no longer uses a production live candidate resolver. Its adapter
opens the selected target once, performs target-local identity and exact Work
Ticket safety checks, clicks once, confirms positive debit/unlock evidence,
and continues normal quota crawling on the same Page. Positive Catalog/live
identity or contract disagreement stops the resource pass and requests a new
full Discovery; a positive `isCharged=false` is reported as a distinct
`work_ticket_cooldown`. The shared resolver framework remains for Zebrack,
whose Discovery cannot classify native per-chapter ticket state.
The generic Executor validates a populated candidate external ID against the
Catalog source before opening a page. Comic DAYS treats charged-without-
`chargedAt` as unknown; the target-local safety path cannot infer a click
baseline. CLI stop-pass output is neutral, while the adapter reason remains
available for operators and metrics.

## Entry-only success diagnostics (2026-10-06)

The generic `BatchExecutor` now best-effort collects the adapter's existing
`collect_debug_metadata()` after a confirmed grant-only entry and writes
metadata-only `diagnostics/entry_trace.json` under that candidate's existing
output directory. The file carries `item_id`, `source_id`, `target_id`, `site`,
and `resource`; collection or write failure never changes the candidate result.
This is a generic hook extension and has no site-name branch. Comic DAYS puts
its bounded `ticket_trace` inside `adapter_debug`, and the existing Runner
failure diagnostics expose the same field under `metadata.json`'s
`adapter_debug`; no capture, retry, pacing, timeout, click, or Catalog
semantics are changed.

## Zeblack Z5 current status (2026-09-30)

### Z5-6 production initial-navigation and Work Ticket flow

The generic `SiteAdapter` contract now has the synchronous
`resolve_initial_navigation_url(source_url)` hook. Its default returns the
canonical `source_url`; `CrawlerRunner` calls it after run/resource validation
and uses the result only for the first browser navigation. `source_url` remains
the identity stored in ProgressStore, CrawlRun, BatchCandidate, and
SourceTarget.

Zeblack stores the canonical viewer target as `_target_url` / `_target_viewer`.
For `quota + work_ticket`, the hook strictly parses that viewer URL and enters
`/title/{title_id}/chapter/list`; malformed, foreign, or non-viewer targets fail
closed without falling back to direct viewer navigation. `direct` and `auto`
retain the viewer URL as the initial browser entry.

The quota Adapter observes live protobuf status and `target.main_name`. For
`TICKET_AVAILABLE`, it validates one visible target chapter row and one exact
mainName descendant, clicks that chapter control once, requires the exact
chapter-list URL to remain, validates the visible modal identity (mainName,
`チケットを使って読む`, `キャンセル`) in one bounded DOM scope, and rejects
point/item/coin/purchase controls. It clicks the exact ticket control at most
once, waits for the same target viewer and stable `page_N` content, and only
then records `AccessConsumption(consumed=True, resource="work_ticket")`.
FREE / RENTAL skips the modal and navigates to the target viewer for normal
runs; entry-only returns `work_ticket_not_needed` without that navigation.
POINT/unavailable statuses retain the existing resource-pass skip behavior.

The observer still owns its existing chapter-list navigation, so quota entry
currently performs an initial Runner list load plus one bounded observer reload.
This is an accepted initial implementation constraint and the observer remains
the live protobuf authority. No real Work Ticket was consumed by this change;
the controlled live click/consumption verification remains a separate follow-up.

### Current live verification: title 66 / chapter 6077

The latest `main` commit `e990c97` was reviewed. Shared-CDP read-only
observation decoded 229 title-66 protobuf records with
`FREE=3`, `RENTAL=0`, `TICKET_AVAILABLE=1`, `POINT=193`, and `COIN=32`; the
oldest/current ticket candidate was chapter `6077`. Bounded singleton
Discovery and Batch planning completed with one `work_ticket` quota candidate,
and the temporary Catalog initially had a pending Item with no quota state,
CrawlRun, or Artifact.

The final preflight immediately before grant-only still saw
`TICKET_AVAILABLE`, but the production `--grant-only work_ticket --limit 1`
run observed `RENTAL` with preexisting same-chapter content and safely skipped
as `work_ticket_not_needed`. No exact ticket click, point/coin/purchase
fallback, `AccessConsumption`, or quota timestamp occurred. A separate normal
run then verified the RENTAL path: no additional ticket click, 19 source-native
JPEG pages at `760x1200`, `next_content`, ZIP Artifact, and `Item=completed`.
Post protobuf state was `RENTAL=1`, `TICKET_AVAILABLE=0`; the transition is
not attributed to an exact ticket action by this run. Work Ticket consumption
remains unverified, so Zeblack Z5 is **BLOCKED**, not COMPLETED.

### Current live verification: title 53 / chapter 4844

The current shared-CDP verification observed 411 title-53 protobuf records.
Before the controlled attempt, counts were `FREE=3`, `TICKET_AVAILABLE=1`,
`POINT=377`, `COIN=30`, `RENTAL=0`; the oldest/current candidate was chapter
`4844` (`標的4 退学クライシス`). Title-top UI independently showed
`チケットでさっそく読もう！ × 1`, but this remains diagnostic only.

Full Discovery and a bounded singleton Discovery completed read-only. The
singleton Batch plan had one eligible quota candidate using `work_ticket`.
The Adapter was corrected so live protobuf status is consulted before locked
viewer `page_N` placeholders are considered preexisting content; viewer
hydration is also bounded before and after the same-page live preflight.

No exact Work Ticket control was clicked. The later post-observation reported
`FREE=3`, `RENTAL=1`, `TICKET_AVAILABLE=0`, `POINT=377`, `COIN=30`, with target
`4844` now `RENTAL`. This transition is not attributed to the read-only or
skipped grant-only checks. The normal RENTAL run then completed with the
site-local ad and last-page interstitial handling, `next_content` stop, 19
source-native JPEG entries, and a present ZIP Artifact. The Item is
`completed`; Work Ticket consumption remains unverified and no quota timestamp
was committed.

Zeblack now has both production Discovery and a registered Batch Site Policy.
Catalog `quota` remains a broad candidate class, while explicit quota runtime
uses a site-local live `title_chapter_list` protobuf preflight. The Viewer
Adapter only attempts a single exact ticket-only control when the target live
status is `TICKET_AVAILABLE`; POINT/COIN/unknown states fail closed or return
the generic resource-unavailable result. Confirmed same-chapter content is
required before `AccessConsumption` is recorded. `work_ticket` is the only
supported Zeblack resource, with no local cooldown/capacity inference and
`after_observed_consumption` persistence. Grant-only reuses the generic
entry-only path and leaves Items pending without packages.

The 2026-09-30 Z5-1 check did not consume a ticket. Human observation confirms
that selecting/opening a `TICKET_AVAILABLE` chapter only reveals the next
entry action; consumption starts only when the exact `チケットを使って読む`
action is clicked. The check stopped before that action, so no ticket action
was performed and no grant-only run was executed.

The later protobuf observation showing the target as `RENTAL` and removing
all `TICKET_AVAILABLE` IDs is not attributed to this read-only check. The
temporary singleton Discovery/Batch plan completed read-only and the
temporary Catalog remained pending. The point path is separate: a point
chapter exposes `ポイントを使って読む`, which is never a valid fallback and
must not be clicked. The existing direct Z3 capture path and Z4 Discovery
boundary remain intact.

## Zeblack Z4-1 status (historical baseline)

Zeblack production Discovery is implemented. The adapter is registered in the
Discovery registry, supports unbounded full/incremental and site-native
bounded Discovery. The current Z5 policy registration is described above.
Discovery validates the chapter-list DOM and the exact
`title_chapter_list` protobuf response before yielding. It uses
`chapter_id` identity, latest-first canonical order, explicit access-mode
mapping, and inclusive viewer URL boundaries. The existing Zeblack Viewer
Adapter and crawl lifecycle are unchanged. Zeblack Site Policy and access
resource consumption are not implemented in this phase.

## Phase 4A Discovery status

`MangaOneDiscoveryAdapter` is now registered for `mangaone`. It reads an
arbitrary chapter URL's `#chapterList` newest-first, follows bounded 10-item
pagination, and uses the chapter id (not the URL) as source identity.
`無料`/`FREE`, `先読`/`先読み`, and unbadged cards map to `free`, `paid`, and
`quota`. Incomplete traversal is not treated as a complete full scan. The
adapter remains Catalog-free and does not own BrowserSession lifecycle; the
minimal `discover` CLI supplies the Page. BookWalker series-scoped Discovery
is now registered. BookWalker Site Policy, grant-less quota consumption, and
automatic Batch execution are implemented, while BookWalker strict
direct/quota product-page entry remains in the BookWalker Adapter. Phase 5A adds
read-only Batch planning and Manga ONE Policy. Phase
5B adds sequential Manga ONE Batch execution around the existing Core.

このファイルはScreenshot Crawler Coreの**現在の実装詳細**と、採用済みのBrowser Session移行方針をまとめる。Core / Runner / browser / output / packaging / diagnostics / resume方針を変更した場合は、このnoteも同じ変更で更新する。

最終同期: 2026-10-02


### Test execution policy（2026-09-27）

テスト分類・選択・実行範囲のauthorityは `docs/TEST_STRATEGY.md`。

2026-09-27の実測では、full pytestは約4分で完走可能だったが、`tests/unit/` に実Chromiumを起動するtestが混在し、productionのpacing / timeoutを実時間で待つtestも存在することを確認した。詳細な測定snapshotは `note/test_suite_audit.md` に保存している。

現在の運用方針:

- 全変更で `pytest -q` を必須にしない
- 開発中は変更した契約に直接対応するtargeted testを使う
- 完了前に影響範囲のUnit / Integrationへ広げる
- shared Core、共通data model、大規模refactor、複数site変更、影響範囲不明ではfull suiteを実行する
- 実browser / DOMを使うものはIntegration相当、`poc/` を直接検証するものはResearch / Probe相当として扱う
- productionの実時間delay / timeoutそのものが検証対象でなければ、testではfake / injection /短いtest-specific timeoutを使う
- 最終報告では実行testsに加え、Integration / Research / Live / full suiteを未実行なら理由を書く

Phase 2Bでは、Research / Probe 4 filesを`tests/research/`へ移動し、mixed 8 filesを
Unit / Integrationへ分割した。Phase 2B-3完了後の実測collectionは785 cases
（Unit 610 / Integration 129 / Research 46）で、targeted / category / full pytestを
passした。`tests/unit/`には実Chromium起動testを残しておらず、browser / DOM boundaryは
`tests/integration/`、`poc/` / probe実装の検証は`tests/research/`に配置している。

`pytest -q tests/unit tests/integration`はproduction regression、`pytest -q tests/research`
はResearch / Probe regression、`pytest -q`はResearchを含むrepository-wide regression
である。Phase 2B-3のruntime baseline（`-p no:warnings`）は Unit 52.48s、Integration
169.99s、Research 0.46s、full 223.66s（通常の`pytest -q`はwarning込み250.67s）だった。
BookWalker AdapterはPhase 2A計画の18 Unit / 25 Integrationに対し、現行testを実際の
browser依存で分類すると17 Unit / 26 Integrationとなる。この1 case差分はtest semanticsを
変えずに解消できないため、classification planのOpen Questionとして残している。

今回は高速化、fixture scope変更、test semantics変更、pytest設定変更、production code
変更を行っていない。browser起動回数、実時間wait、timeout / pacingの最適化はPhase 3
以降の課題である。

### Phase 3A test runtime optimization (2026-09-28)

Phase 3A removed real production inter-candidate pacing waits from the five
resource-pass and grant-only orchestration tests in
`tests/unit/test_cli.py`. Those tests now replace the CLI module's async sleep
with a no-op async fake, while retaining their ordering, replan, limit,
resource-exhaustion, and failure assertions. The existing pacing contract
test remains responsible for checking the configured delay, seconds
conversion, between-candidate placement, and no-delay-after-the-last-candidate
behavior. The production default `inter_candidate_delay_ms = 3000` is
unchanged.

Measured runtime:

| Scope | Before | After |
| --- | ---: | ---: |
| `tests/unit/test_cli.py` (63 cases) | 25.75s | 1.11s |
| `tests/unit` (610 cases) | 52.48s | 31.10s |
| full pytest, `-p no:warnings` (785 cases) | 223.66s | 198.89s |
| full `pytest -q` (785 cases) | 250.67s | 205.04s |

The full-suite slowest tests remain Integration/browser wait tests; Phase 3A
did not change browser fixtures, Manga ONE timeouts, production runtime
behavior, pytest configuration, or test counts.

### Phase 3B test-specific Integration wait optimization (2026-09-28)

Phase 3B shortened only waits that are not themselves the contract under test.
The changed Integration tests use existing test-side configuration seams:

- Manga ONE viewer-missing failure uses `page_change_timeout_ms=200`.
- Manga ONE grace-period tests use `page_change_timeout_ms=500` and
  `end_grace_ms=200`.
- Local viewer Runner tests use `page_turn_delay_ms=0` because page-turn pacing
  is not their contract; state transitions, same-content guards, and max-page
  assertions remain unchanged.
- The Magapoke terminal-card Runner test uses
  `page_change_timeout_ms=500` and `page_turn_delay_ms=0`; its 150 ms fixture
  transition and terminal-card assertions remain unchanged.

Production timeout/grace defaults, polling algorithms, browser fixture scope,
Chromium launch count, and production code are unchanged. No pytest-only
environment branch or global test mode was added.

Direct Phase 3B measurements before the change were 129 Integration cases in
177.83s and 785 full cases in 208.56s with `-p no:warnings`. After the change,
Integration remained 129 cases and ran in 139.70s; the full warning-suppressed
run was 790 cases in 181.43s, and standard `pytest -q` was 790 passed in
168.58s with 2,774 warnings.

The full collection became 790 during this work because a separate, user-owned
five-case Research addition (`tests/research/test_jumpplus_vertical_probe.py`
and `poc/jumpplus_vertical_probe.py`) appeared in the working tree. That
addition and its `note/04_jumpplus.md` update are not part of Phase 3B and were
not modified or staged. The Phase 3B changes themselves preserve the previous
785-case taxonomy: Unit 610 / Integration 129 / Research 46.

### Phase 3C-1 Magapoke browser lifecycle proof (2026-09-28)

The Magapoke Adapter browser tests now use module-scoped Playwright and Browser
fixtures, with a fresh function-scoped BrowserContext and Page for every test.
The target file remains 43 cases. Direct measurement changed the target-file
runtime from 29.15s to 8.39s; lifecycle instrumentation showed Playwright
starts 43 -> 1, Chromium launches 43 -> 1, and Context/Page creation at 43 / 43.

The repeated target-file runs were 9.08s and 9.11s, and the full Integration
suite ran 129 passed in 121.34s. The standard full suite ran 801 passed in
152.09s with 2391 warnings. No order dependency, browser crash, cleanup leak,
or Chromium skip was observed. The target file uses an explicit module async
loop scope to keep module-owned Playwright objects on the same loop; pytest
configuration was not changed.

Only `tests/integration/test_magapoke_adapter_browser.py` and this note were
changed for Phase 3C-1. Production code, test semantics, timeout/grace values,
other Integration files, and shared `conftest.py` were not changed. The
current observed collection is Unit 610 / Integration 129 / Research 62 = 801;
the Research count was not modified by this Phase. BookWalker rollout remains
Phase 3C-2 and is pending.

### Phase 3C-2 BookWalker browser lifecycle rollout (2026-09-28)

The three BookWalker browser-backed Integration files now use the shared
`tests/integration/conftest.py` lifecycle primitives. The fixture scopes remain
module-scoped Playwright and Browser, with function-scoped fresh
BrowserContext and Page. No Context or Page is shared. BookWalker-specific
routes, HTML, Catalog setup, and capture helpers remain local to each test
file.

Before -> after measurements:

- Adapter: 26 cases, 26 -> 1 Playwright/Chromium lifecycle, 32.30s -> 18.50s.
- Discovery: 19 cases, 19 -> 1 Playwright/Chromium lifecycle, 27.11s -> 17.55s.
- Original Capture: 4 cases, 4 -> 1 Playwright/Chromium lifecycle,
  2.57s -> 0.98s; its three test-local extra Context/Page pairs were retained.
- Combined target: 49 passed; repeated runs 36.74s and 36.37s.
- Integration: 121.34s -> 90.79s in the first after run; the final
  verification run was 101.65s for 129 passed due to unrelated local-viewer /
  wait-test runtime variance.
- Full: the latest run was 816 passed in 149.14s with 2079 warnings. Latest
  collection was Unit 624 / Integration 129 / Research 63 = 816; Unit and
  Research changed because unrelated user-owned changes appeared during the
  work and were not modified.

`--setup-show` confirmed three module Playwright fixtures, three module Browser
fixtures, and 49 function Context/Page fixture invocations. Repeated and full
runs showed no order dependency, loop ownership error, browser crash, cleanup
leak, or Chromium skip. The Original Capture extra Page is explicitly closed
before its Context. Production code, pytest configuration, timeout/grace
values, assertions, parametrization, and non-BookWalker Integration semantics
were not changed in the Phase 3C-2 snapshot; Phase 3C-3 is recorded below.

The BookWalker Adapter retains its historical 800x600 viewport through a
file-local function-scoped `browser_page` fixture backed by the shared module
Browser. The generic integration fixture keeps the Playwright default viewport
for BookWalker Discovery and Original Capture.

No new test case was added for this follow-up; the existing Adapter tests and
the 49-case BookWalker group pass with the restored viewport.

### Phase 3C-3 remaining Integration browser lifecycle rollout (2026-09-29)

The final six targeted browser-backed Integration modules now use the shared
module-scoped Playwright/Browser lifecycle from
`tests/integration/conftest.py`, while keeping fresh function-scoped
BrowserContext and Page objects. The migrated files and current case counts
are:

- AccessGuard browser: 1
- generic local viewer: 19
- Magapoke Discovery browser: 6
- Magapoke local viewer: 3
- Manga ONE Adapter browser: 7
- Manga ONE Discovery browser: 1

The 37 cases therefore use six module Playwright starts, six Chromium launches,
and 37 fresh Context/Page pairs. The following three files retain their
historical 800x600 viewport in file-local fixtures:

- `test_local_viewer_flows.py`
- `test_magapoke_local_viewer.py`
- `test_mangaone_adapter_browser.py`

AccessGuard, Magapoke Discovery, and Manga ONE Discovery use the generic
Playwright-default viewport. No Context or Page is shared, and no session scope
or pytest configuration change was introduced. Phase 3C is now complete.

Measurements:

- Before: 37 passed in 39.74s, with 37 per-case Playwright/Chromium starts.
- After: 37 passed in 40.54s; repeated runs were 41.21s and 31.08s.
- Integration: 129 passed in 80.75s in the final run.
- Full: 816 passed in 115.95s, with 1770 warnings.
- Collection: Unit 624 / Integration 129 / Research 63 / Total 816.

The six-file aggregate is affected by existing test-body wait and local-viewer
transition costs, so its direct runtime did not improve monotonically. The
lifecycle proof is the reduction from 37 per-case browser owners to six module
owners while preserving fresh Context/Page isolation. Repeated target,
Integration, and full-suite runs showed no order dependency, event-loop
ownership error, browser crash, cleanup leak, or Chromium skip. Phase 3C is now
complete. The remaining Integration files were not changed, and no
session-scoped or cross-module Browser fixture was introduced.

### Phase 3D-0 runtime reassessment (2026-09-29)

Phase 3C-complete Integration runtime was remeasured without changing test or
production behavior. Three Integration runs were 81.83s, 90.72s, and 87.50s
(median 87.50s) for 129 passed; the full warning-suppressed suite was 817
passed in 120.47s. A temporary timing hook measured setup 11.298s, call
65.966s, and teardown 1.954s, confirming that test-body call time now
dominates. Phase 3D remains assessment-only; detailed slow-test and ROI
analysis is recorded in `note/test_runtime_phase3d_assessment.md`.

### Phase 3D-1 BookWalker strict-entry test-side timing (2026-09-29)

The BookWalker Adapter browser test keeps its 26 cases, shared Browser
lifecycle, production defaults, and two stable candidate samples. Six
timing-independent successful selection tests explicitly use a test-side
10ms initial settle and 20ms candidate poll interval. Persistent rejection
cases leave the timing arguments unset and therefore inherit the adapter's
production 250ms/100ms defaults because applying fast polling broadly increased
repeated DOM scans rather than reducing runtime. The helper uses `None`
defaults and writes instance attributes only for explicitly supplied overrides.
The delayed-Maruyomi and transient-duplicate timing cases retain their
300ms/350ms fixture delays and timing semantics.

The target file improved from a 17.98s median to 16.32s over three-run
measurements, a demonstrated 1.66s saving. Integration then passed 129 cases
in 87.80s, and the current full suite passed 821 cases in 115.64s. Current
collection is Unit 624 / Integration 129 / Research 68 / Total 821; the
Research increase is outside this Phase. No production code, pytest
configuration, fixture scope, or other browser-backed test was changed. The
detailed classification and ROI decision are recorded in
`note/test_runtime_phase3d_assessment.md`; no broader Phase 3D rollout is
currently justified.

The follow-up maintenance correction leaves `_initialize_strict()` timing
arguments unset by default and applies instance overrides only when explicitly
provided. The current verification passed 26 BookWalker Adapter cases, 129
Integration cases, and 822 full-suite cases; collection is Unit 624 /
Integration 129 / Research 69 / Total 822. This correction makes no new
runtime claim and does not change production defaults or test semantics.

## 1. Scope

Coreはサイト固有DOMやページ送りを判断しない。共通処理を担当する。

主な責務:

- Playwright browser/context接続補助
- URL navigation
- Site Adapter呼び出し
- PageState loop
- capture / artifact保存（default PNG、Adapter direct captureではformat metadataを保持）
- SHA-256 fingerprint
- duplicate / same-content guard
- manifest / progress
- diagnostics
- max_pages / retry / timeout
- 正常終了後のZIP packaging

Site固有selector、END判定、NEXT操作は `site_adapters/<site>/` の責務。

## 2. Main modules

```text
src/screenshot_crawler/core/
├─ browser.py       browser launch / CDP endpoint / CDP connection / session
├─ capture.py       Locator / canvas capture, artifact save
├─ diagnostics.py   screenshot / HTML / metadata / error
├─ errors.py        crawler errors
├─ fingerprint.py   SHA-256
├─ models.py        RunConfig / identity / context / captured page
├─ packaging.py     manifest-based ZIP / library output
├─ progress.py      manifest / progress / new-run safety
├─ runner.py        state machine
└─ state.py         PageState
```

`site_adapters/base.py` がAdapter contract。

## 3. Browser Session Model

### 3.1 採用済みの目標仕様

Real-site automationは、1つの共通Crawler Chrome/profileへCDP接続し、そのChromeをPlaywrightで操作する。

```text
Crawler Chrome
└─ .chrome-crawler/
      ├─ bookwalker.jp session
      ├─ manga-one.com session
      └─ other site sessions
          ↑
          │ CDP
          ↓
Playwright Browser / Context / Page
          ↓
Core Runner
          ↓
Site Adapter
```

役割:

- CDP = Chromeへの接続transport
- Playwright = 通常のbrowser/site操作API
- Adapter = site固有viewer logic

Raw CDP ProtocolはPlaywrightで代替できない場合だけ使う。

### 3.2 現行実装

real-siteの標準launcherは `scripts/start_crawler_chrome.ps1` である。repository root基準の
`.chrome-crawler/` profileを使い、default port `9222`でshared Crawler Chromeを起動する。
指定portに既存CDP listenerがある場合はChrome processのcommand lineでportとshared profileを確認する。一致すれば既存Chromeを再利用し、一致しない・確認できない場合は二重起動せずerrorで停止する。

起動時の `--user-data-dir` はquoteして渡す。起動後も `/json/version` 応答だけを成功条件にせず、同じprocess確認を再実行し、remote debugging portとshared profileの一致を確認してから成功メッセージを表示する。

```text
scripts/start_crawler_chrome.ps1
.chrome-crawler/
```

BookWalker/Manga ONEのshared-profile live verificationが完了しているため、real-site launcherはこの共通launcherのみを標準とする。移行前に作成されたsite-specific profile directoryが残っていても、launcherは自動削除しない。

現行CLIのendpoint解決も:

```text
--cdp-endpoint
→ site-specific *_CDP_ENDPOINT
→ CRAWLER_CDP_ENDPOINT
→ http://127.0.0.1:9222
```

で統一されている。CLI指定を最優先し、site-specific endpointは例外overrideとして
維持する。`.env`の値よりプロセス環境変数が優先される。

Phase 1/2では、次を実装済みである。

```text
CRAWLER_CDP_ENDPOINT
core.browser.resolve_cdp_endpoint()
core.browser.BrowserSession
```

`CRAWLER_CDP_ENDPOINT` はshared Crawler Chromeを指す標準global endpointである。
site-specific endpointは特殊なprofile/account等のための例外overrideとして残している。

既存CDP listenerがある場合、launcherはprocess command lineのremote debugging portと
`--user-data-dir`をshared profileと照合する。一致しない、またはprocessを確認できない場合は
既存Chromeを黙って再利用せずerrorで停止する。

### 3.3 移行時の非変更範囲

Browser Session統一のために以下を変更しない。

- BookWalker capture方式
- BookWalker END/NEXT_CONTENT
- Manga ONE capture方式
- Manga ONE image-disappearance END heuristic
- Runner fingerprint dedupe
- output/packaging semantics

Browser/session管理だけを差し替える。

## 4. Authentication model

login sessionのauthorityは共通Chrome profile。

Chrome自身がsiteごとに:

- Cookie
- localStorage
- IndexedDB
- その他browser storage

を保持する。

Crawlerはsite別storage-state JSONを標準管理しない。

login CLIは:

```text
Browser Session Layer
→ Playwright Page
→ site-specific login handler
```

で動く。

real-siteのcrawl/loginは `BrowserSession.connect()` でCDP接続し、既存の
BrowserContextからPageを作成する。crawlが作成した作業Pageは終了時に閉じる。
loginは別siteの既存タブを再利用せず、常にlogin用new Pageを作成して終了時に閉じる。
BrowserSessionの終了はPlaywright接続を切断するだけで、remote Chrome processは閉じない。

Probeのnative Playwright launchでは `launch_browser()` / `create_browser_context()` を使う。
`connect_browser()` と `close_browser()` はProbeおよびBrowserSessionで使うため残している。
repository-wideでcall siteがなかった `BrowserSession.existing_page()` と `create_page()` は削除した。
保存済みauth-stateの補助 (`auth.storage` / `save_auth.py`) もProbe・local auth workflowで到達可能なため、
real-site標準がChrome profileであることだけを理由に削除しない。

credentialsのinputは `.env` 等を使ってよいが、session保存はChromeへ任せる。

CAPTCHA / MFA / validation errorは自動突破しない。

## 5. CDP endpoint policy

現行の優先順位:

```text
--cdp-endpoint
→ <SITE>_CDP_ENDPOINT
→ CRAWLER_CDP_ENDPOINT
→ http://127.0.0.1:9222
```

通常はglobal endpointだけを使う。

site-specific overrideは例外用:

- 別account
- extension差
- browser setting差
- session分離
- 共通profileでは正常動作しない場合

## 6. Adapterとの境界

Adapterへ渡るものはPlaywright `Page`。

Adapterは:

- Locator取得
- click / keyboard / mouse
- wait
- evaluate
- capture target決定
- END / NEXT_CONTENT判定

を行う。

Adapterは:

- Chrome launch
- profile選択
- endpoint解決
- `connect_over_cdp()`
- BrowserContext lifecycle

を行わない。

## 7. PageState loop

PageState:

```text
CONTENT
AD
END
NEXT_CONTENT
LOADING
UNKNOWN
```

Runner概念フロー:

```text
ensure output dir is new/empty
prepare_page
page.goto
adapter.initialize
initial context
ProgressStore作成

loop:
    detect state

    END / NEXT_CONTENT
        -> normal return

    UNKNOWN
        -> error + diagnostics

    AD
        -> go_next + wait_for_change

    CONTENT
        -> max_pages guard
        -> context確認
        -> identity取得
        -> one/multiple capture targets取得
        -> capture
        -> fingerprint dedupe
        -> artifact bytes + manifest/progress保存
        -> go_next + wait_for_change
```

LOADINGはbounded retryし、解消しなければ `PageChangeTimeoutError`。

## Adapter timeout layering

`RunConfig.page_change_timeout_ms` is the adapter-owned operation deadline. The
Core `CrawlerRunner._adapter_call()` wrapper uses the adapter deadline plus
`adapter_timeout_grace_ms` (default 2,000 ms). Adapters may override
`get_initialize_timeout_ms()` when initialization sequences multiple bounded
phases; the base implementation returns the usual page-change budget, so other
adapters retain their existing timeout. Magapoke uses a larger bounded outer
budget for access readiness, click confirmation, and viewer stabilization.
Page-change waits still use their original per-phase budget, and the grace
applies to all adapter calls.

## 8. max_pages

`max_pages` は保存ページ数の安全上限。

重要な境界仕様:

- `saved == max_pages` のあと次stateが `END` / `NEXT_CONTENT` → 正常終了
- `saved == max_pages` のあとさらに `CONTENT` → `MaxPagesExceededError`
- `max_pages`を超えるPNGは保存しない

## 9. Identity / fingerprint / duplicate

`ContentIdentity` はpage id / page number / source id等を保持し、主に:

- Adapter change detection
- manifest
- debug / progress

へ使う。

**保存duplicateのauthorityはcapture bytesのSHA-256 fingerprint。**

identityが異なっていてもfingerprintが同一ならduplicate扱い。

これは既存BookWalker / Manga ONEの動作互換を優先した現行仕様。

## 10. same-content guard

新しいcaptureが得られない状態が続いた場合は `same_content_count` を増やす。

既定 `max_same_content = 3`。

上限到達で `PageChangeTimeoutError` として停止する。

## 11. Context / NEXT_CONTENT

開始時 `ContentContext` と現在contextのstrong fieldを比較する。

strong fields:

- content_id
- work_id
- episode_id
- chapter_id

同じfieldが開始時・現在とも存在し、値が変わった場合だけcontext change。

optional情報が後から埋まっただけではNEXT_CONTENTにしない。

## 12. Capture

基本はLocator単位capture。

Canvas targetの場合、`capture.py` はcanvas raw PNG bufferを取得できる。
`toDataURL()` がtainted canvasの `SecurityError` やPlaywright evaluate errorで
失敗した場合は、同じLocatorの `screenshot()` へsite-neutralにfallbackする。
これによりcross-origin画像を描画するcanvasも、viewer外を撮らずに保存できる。

Adapterは `get_capture_targets()` で複数targetを返せる。保存順はAdapterが返した順。

一時targetは `cleanup_capture_targets()` で後始末する。

Adapterは必要な場合だけ `capture_page(page)` をoverrideできる。非`None`の非空
`tuple[CaptureResult, ...]`を返した場合、CoreはLocator captureを行わず、その結果を同じ
fingerprint / manifest / page dimension処理へ渡す。`None`、`CaptureUnavailableError`、Coreの
bounded timeoutでは従来の `get_capture_targets()` → `capture_locator()`へfallbackする。
fallback後のcapture失敗は通常のrun errorとし、直接capture hookが作ったtemporary resourceの
cleanupはhook側の責任とする。Base Adapterは`None`を返すため、overrideしないsiteの挙動は維持する。

## 13. Run output safety

新規runの `output_dir` は、存在しないか完全に空でなければならない。

既存ファイルが1つでもある非空directoryは `RunAlreadyExistsError` で拒否する。

目的:

- 前runのcapture artifact混入防止
- manifest/progress上書き防止
- user file削除防止

`ProgressStore` も既存manifest/progressを暗黙上書きしない。

## 14. Manifest / progress

実行中:

```text
<output_dir>/
├─ page-0001.png  # default Locator capture
├─ page-0002.webp # source-native Adapter captureの例
├─ manifest.json
├─ progress.json
└─ diagnostics/  # failure時に作られる場合あり
```

manifestは保存ページ一覧のauthority。

各page entryは `mime_type` と `file_extension` を持つ。Locator / canvas captureの
defaultは `image/png` / `.png` で、Adapterのdirect captureはsource-native artifactの
formatをそのまま記録できる。Runnerはこのextensionで連番ファイル名を生成し、
packagingはmanifest記載の安全なJPEG/PNG/WebP artifactだけを対象にする。

`progress.json` はlast sequence / identity / fingerprint / contextを持つが、**自動resume機能ではない**。

JSON更新はtemporary file → `os.replace`。

## 15. Resume

現行ではresume未実装。

- 非空run dirは拒否
- 既存manifest/progressを読み込んで続行しない
- 暗黙resumeしない

将来追加するなら `--resume` 等で新規runと明示的に分離する。

## 16. Packaging

正常な `END` / `NEXT_CONTENT` 後だけZIP化する。

ZIP対象はdirectory globではなく `manifest.json` の `pages[].file` がauthority。

安全ルール:

- manifest外artifactをZIPへ入れない
- manifest記載artifact欠落はfail
- unsafe path拒否
- manifest file重複指定拒否
- 既存同名ZIPは上書きしない

ZIPはlibrary treeへ保存し、completion status JSONを別途残す。ZIP内部の画像は
manifestの`pages[].file`に記載された相対パスをそのまま使い、archive stemの
top-level directoryは作成しない。

Batch Candidateは必要な場合だけsite-neutralな`artifact_prefix`と
`artifact_disambiguator`をpackagingへ渡せる。`artifact_prefix`はpositionを
最小3桁で表すarchive filename全体の先頭prefixであり、metadataの`title` /
`order` / `author` / `genre`を変更しない。Batch Plannerの`order`は生の
`Item.order_label`を維持し、positionはshared `archive_position_prefix()`で
`BatchCandidate.artifact_prefix`へ分離する。labelなしはprefixだけになり、
positionがNULLなら従来のorder labelを維持し、positionを`order_key`やID等から
推測しない。Core packagingのprefixはarchive/status stemだけに作用し、library
directoryは従来どおりgenre/titleである。
Plannerはsite-scoped snapshotの全status Item/Sourceを対象に、既存の
`archive_stem()`でsanitized base stemを比較する。同一Work内でdistinct Item IDが
衝突するgroupのSourceだけへ`{site}-{Source.external_id}`を設定し、同一Itemの複数
Sourceだけではsuffixを付けない。Manga ONE/Magapoke専用のnaming workaroundは廃止した。
ZIP内部の画像はmanifestの相対パスをそのまま使い、作品stemのtop-level directoryは作成しない。
archive filenameとcompletion status JSONのfilenameは同じstemを使う。stemは
`artifact_prefix-[title if sanitized title length < 50]-order-author[-artifact_disambiguator]`
である。正規化・サニタイズ後タイトルが50文字以上の場合だけtitleを省略し、
title自体は常にlibrary directoryに含める。50文字ちょうども省略対象である。
filename要素がすべて空の場合は`archive`をfallbackにする。statusは
`output/crawl-status/<genre>/<title>/<stem>.json`へ保存し、Work間の同じstemでも衝突しないようにする。destination存在時の
`FileExistsError`と自動連番なしの安全性を維持する。既存archive/status/Artifact
locatorは通常Batchで変更せず、明示的なP4 renumberだけが現在のstemへ移行する。

既存archiveのP4 renumberは `scripts/renumber_archives.py` が薄いCLI wrapperとして提供する。
`--work-key`、`--site`、両方のAND、または`--all`の明示scopeが必須で、defaultはdry-run、
変更は`--apply`時だけである。current ArtifactはSourceごとに、archive/zip Artifactを生成した
最新successful CrawlRunから最大1件だけ選ぶ。新しいsuccessful runにarchiveがなければ古い
successful runを探すが、選択後のlocator欠損では歴史Artifactへfallbackせず`MISSING`とする。
`display_position=NULL`、複数archive Artifact、非filesystem、locator欠損はそれぞれ安全にskipする。
old pathは常に`Artifact.locator`、new pathはそのparent内のP3 shared naming stemであり、
library treeのdirectory移動やZIP再走査は行わない。P3のsame-site Work/stem collision snapshotは
P4でもfiltered subsetではなく全site snapshotから計算する。

P4はscope全体を先にpreflightし、内部/外部target collision、collision dependency、status target
collisionを検出してoverwriteを拒否する。実行時はZIPを短い
`.archive-renumber-{artifact_id}.tmp`へ、matching status JSONを
`.status-renumber-{artifact_id}.tmp`へ移してからfinalへ移す二段階renameを使う。
rollback時も`.archive-rollback-{artifact_id}.tmp`と
`.status-rollback-{artifact_id}.tmp`を分離する。元の長いbasenameはtemp名へ含めない。
`output/crawl-status/<genre>/<title>/<old-stem>.json`はJSONの`archive_path`がold
Artifact locatorと同一fileを指す場合だけmatchingとする。明示的なrenumberは旧形式の
`output/crawl-status/<old-stem>.json`も後方互換で確認し、matching時だけrenameして`archive_path`のみ
更新する。missing/mismatch statusはwarningでZIP renameをblockしない。Catalog側は
`update_artifact_locators()`のcompare-and-set一括transactionでlocator/updated_atだけを更新し、
SHA-256、byte size、state、CrawlRun、Item、historical Artifactを変更しない。Catalog更新失敗時（SQLite由来を含む通常の
Python例外）はZIP/statusを二段階rollbackし、成功時は明示ERROR、失敗時は`RECOVERY_REQUIRED`と復旧pathを報告する。
実Catalogや実archiveへの`--apply`は未実行である。

既存ZIPの移行用に、`scripts/flatten_zip_archives.py`を提供する。指定directory配下を
再帰検索し、画像artifactだけが同じ1つのtop-level directory配下にあるZIPから、その1階層だけを
除去して元ZIPを安全に置換する。flat済み、曖昧なtop-level、unsafe path、collision、破損ZIPは
変更せず、`--dry-run`ではFIX / SKIP / ERROR判定とsummaryだけを表示する。画像データは
読み書きするが、画像デコード・再エンコードやCatalog / crawler本体の更新は行わない。

## 17. Intermediate directory cleanup

ZIP作成後、source crawl directoryを削除するのは、directory内容が次だけの場合に限る。

- `manifest.json`
- `progress.json`
- manifest記載page artifact

余分なartifact、diagnostics、user file、その他directoryがあればsource全体を `rmtree` しない。

失敗runは残す。

## 18. Diagnostics

現在の `write_diagnostics()` が保存するもの:

```text
screenshot.png
page.html
metadata.json
error.txt
```

既知の制約:

- diagnostics pathはrun-specific subdirectoryを自動生成しない
- `SiteAdapter.collect_debug_metadata()` is collected into failure diagnostics under
  `adapter_debug`; confirmed grant-only runs additionally write the generic
  metadata-only `diagnostics/entry_trace.json`.
- diagnostics保存失敗は元例外を隠さない

## 19. CLI / packaging flow

The crawl CLI closes the worker Page and disconnects the Playwright/CDP
session before running the filesystem-only `package_crawl_output()` step. This
keeps delayed browser events from writing to a transport that is already being
torn down. The remote Crawler Chrome process itself is never closed.

現行real-site crawl:

```text
CLI
 -> endpoint resolution
 -> BrowserSession.connect()
 -> existing BrowserContext
 -> crawler/login Page
 -> CrawlerRunner.run
 -> END / NEXT_CONTENT
 -> crawler Page close
 -> package_crawl_output
 -> Crawler Chromeは残す
```

主なcrawl引数:

```text
--site
--url
--output-dir
--diagnostics-dir
--library-dir
--max-pages
--max-same-content
--access-strategy auto|direct|quota
--title
--author
--order
--genre
--env-file
--cdp-endpoint
--keep-open
```

2026-09-17時点で、`access_strategy` とoutput metadata override用のCLI/API inputは実装済みである。manual crawlのdefaultは`auto` + metadata未指定で、従来のURL-only挙動を維持する。

現行のRunConfigは、概念上のCrawl Request入力として次を保持する。

```text
access_strategy = auto / direct / quota
optional output metadata:
  title
  author
  order
  genre
```

手動crawlのdefaultは `auto` + metadata未指定とし、現行挙動を維持する。

## 20. Tests

Unit testsで主に確認するもの:

- fingerprint
- capture
- Runner guards
- max_pages境界
- duplicate / same-content
- progress safety
- packaging / manifest validation
- site parser/helper

Browser Session共通化で現在確認しているもの:

- endpoint precedence（CLI > site override > global > default）
- BookWalker / Manga ONEが同じresolverを使うこと
- shared context/page取得
- remote Chromeをcloseしない
- login/crawl共通BrowserSession
- Adapterがbrowser接続方式へ依存しない

2026-09-17にshared `.chrome-crawler/`でBookWalker/Manga ONEのlogin・crawl・session共存を確認済みである。
loginは既存tabを再利用せず専用new Pageを使い、Pageだけをcloseしてremote Chromeを維持する。
両siteのcapture・navigation・END behaviorに回帰はない。

## 21. Known maintenance items

- `BrowserSession`の不要Page helper再発防止
- explicit resume
- diagnostics run directory分離
- config.yaml整理
- identity/fingerprint dedupe再検討
- GitHub CI
- tracked `.egg-info` 整理

これらを変更した場合は、このnoteを必ず更新する。

## Catalog v6: display position / archive naming / status expansion

**P1-P4 IMPLEMENTED; P5 NOT YET IMPLEMENTED.** The adopted implementation plan is:

```text
note/07_catalog_position_archive_plan.md
```

The plan bundles Source-scoped display positions, position-prefixed archive naming,
existing-archive renumber tooling, and Item status expansion
(`pending | completed | skipped | external`) plus `items.note`.
Catalog schema v6, the Item status/note service and CLI, Source display-position
storage/validation, v5 -> v6 migration, CSV export fields, Discovery position
assignment, and P3 position-prefixed Batch archive naming are implemented.
Existing archive renumbering, current Artifact locator updates, and safe matching
crawl-status JSON rename are implemented as the local-only
`scripts/renumber_archives.py` maintenance command. P5 real Catalog/output rollout
and live verification remain planned.
P4 temporary sibling paths use short Artifact-ID-based names without copying the
archive basename, so long Windows archive paths can complete the two-stage rename
and rollback without hitting the legacy path-length limit.

## 22. Discovery / Catalog / Batch（Watchlist + Catalog + Discovery + Batch v3実装済み）

2026-10-02時点では、Watchlist + Catalog基盤、Crawl Requestの最小基盤、site-neutral Discovery framework、Comic DAYSを含む各siteのDiscovery / Site Policy registry、Phase 5Aのread-only Batch Planner、Manga ONE・BookWalker Batch Executor、BookWalker Adapterのstrict direct・quota product-page entryが実装済みである。Comic DAYSは公式free-only Atomの再検証を行うdirect専用Adapterとして登録され、ticket/point/coin/quota resourceは扱わない。BookWalkerは05:00 JSTのsite-wide 1枠local safety policyを使い、quota開始をreader entry前に永続化する。実サイトquota clickは未確認である。

Comic DAYSのC3実サイトE2Eでは、明示的な`catalog_comicdays.sqlite`と隔離watchlistを使い、登録済みDiscoveryが79件（free 4 / unknown 75）をCatalogへ同期した。通常のBatch Plannerはfree targetをdirect・`consumes_quota=false`で選択し、登録済みBatch ExecutorがCrawlerRunner、packaging、CrawlRun / Item / Artifactの成功確定まで完了した。実行結果は32 native PNG、area 1..32、`END`、CRC・manifest fingerprint・dimensions一致である。通常の`catalog.sqlite`とroot `watchlist.yaml`はこのE2Eの入力にしていない。

The dated Japanese C3 paragraphs immediately above are historical snapshots.
Their direct-only/free-only and no-ticket statements are stale and must not be
used as the current contract; the current behavior is the non-deferred,
one-Catalog-candidate Work Ticket flow below.

### Current Comic DAYS Batch authority

The older C3 paragraph above describes the former free-only implementation and
is historical. Current Comic DAYS Discovery full classifies the complete
first-party listing, and `quota_limit=1` keeps one Work Ticket candidate per
work in existing Catalog order. Quota execution is non-deferred: the adapter
does not run a live candidate resolver, opens the Planner-selected target once,
validates its target-local identity and exact Work Ticket contract, confirms
positive debit/unlock evidence, and continues normal crawling on the same Page.
Catalog/live identity or contract disagreement stops the resource pass with
`comicdays_discovery_refresh_required`; `isCharged=false` is the separate
`work_ticket_cooldown` state. The generic resolver remains for Zebrack, whose
Discovery cannot classify native per-chapter ticket state.

authority:

- `docs/SPEC.md`
- `docs/ARCHITECTURE.md`
- `docs/DISCOVERY_AND_BATCH.md`
- `docs/DECISIONS.md`

### 22.1 Watchlist（実装済み）

`WatchlistService`（`src/screenshot_crawler/watchlist/`）がhuman-managed `watchlist.yaml`を扱う。既定pathはcurrent directoryの`watchlist.yaml`で、CLIの`watch`配下では`--watchlist`でoverrideできる。schemaは`targets` listとrequired `key` / `work_key` / `site` / `url` / `label`、optional `enabled`（default `true`）である。required textは空文字を許さず、keyはlist内で一意で、duplicate・malformed YAML・不正targetは明示エラーにする。

CLIは`watch list`、`watch add`、`watch remove`、`watch enable`、`watch disable`を提供する。書き込みは同一directory内のtemporary fileをfsyncして`os.replace`する。Watchlist操作はCatalogを読み書きせず、remove/disableでもCatalog rowを削除しない。

### 22.2 Catalog（Schema v6 P1実装済み）

P1 export detail: `items.csv` includes `note` and `sources.csv` includes
`display_position`; NULL values are emitted as empty CSV fields. P2 adds the
atomic `CatalogService.set_source_display_positions()` API. It validates all
positions and Source identities for `(site, discovery_key)` before updating all
rows in one transaction and refreshing `updated_at`; empty assignments are a
no-op and duplicate numeric positions are permitted.

`CatalogService`（`src/screenshot_crawler/catalog/`）がSQLite connection lifecycle、foreign key enforcement、schema initialization、v6 CRUDを集約する。既定DB pathは`catalog.sqlite`で、`initialize()`または最初のservice operationで初期schemaを作成する。通常のCatalogService / Discovery / Batch / Exportはunsupported schemaをmigrationせず拒否する。v3 / v4 / v5からの更新は明示的な`catalog migrate`で行う。

Schema v6は`works`、`items`、`sources`、`source_targets`、`crawl_runs`、`artifacts`、`quota_resource_states`の7 domain tableを持つ。Workがstableな`work_key` / title / author / genreを保持し、ItemはWork配下の取得単位として`item_title`、kind、order、status、genericなoperator noteを保持する。`items.status`は`pending | completed | skipped | external`で、通常Batchの候補は`pending`だけである。`completed`以外へ変更すると`completed_at`はNULLになり、`completed`では取得時刻を設定できる。Artifactの移動・missing・deletedではpendingへ戻さない。

`Source`のidentityは`(site, external_id)`で、access stateとquota local stateを分離する。`update_source_external_state()`はquota stateを変更せず、`record_quota_access()`はquota stateだけを更新し、`clear_quota_access()`は指定timestampとのcompare-and-setが成功した場合だけquota stateをNULL化する。`mark_sources_unavailable_except()`は指定Discovery scope内のmissing sourceだけをunavailable化する。

`source_targets`はopaqueな`backend` / `target_key` / `locator`を保持し、identityは`(source_id, backend, target_key)`である。`CatalogService`はcreate/upsert/find/get/listを提供するが、target selectionやlocatorの解釈は行わない。

`crawl_runs`はItem/Source/Targetの整合性を検証して作成時snapshotを保存し、`running -> succeeded|failed`だけを許可する。`artifacts`はbinary本体を保存せず、SHA-256、byte size、storage backend、locator、stateを保持する。手動importのためcrawl runなしを許容し、Artifact更新はItem/CrawlRun statusを変更しない。

Phase 1でCatalog packageをv3へ移行し、Phase 2でWatchlist / DiscoveryをWork-aware化し、Phase 3でBatch Planner / ExecutorをCrawlRun / Artifactへ接続した。Phase 4ではCatalog Exportを6 CSVのread-only snapshotとして実装した。

Batch Planner用に `read_works_items_sources_and_targets(site=...)` を提供する。これはread-only接続でWork / Item全件、指定siteのSource、関連するSourceTargetを取得し、Plannerはraw SQLiteへ直接アクセスしない。`site=None`では全siteのSource/Targetを同じread-only snapshotで取得でき、P4 maintenanceの`--all` scopeに使う。指定siteのSourceを1件以上持つItemだけをsite-scopedな母集団にし、別site専用Itemとsourceなしのorphan Itemを`no_source` skipに含めない。未存在・未初期化Catalogを作成せず、Batch planによるCatalog副作用を防ぐ。

Catalog確認用に `catalog export` CLIを提供する。`catalog/export.py` の `export_catalog_csv()` はSQLiteをread-onlyで検証・読み込みし、`catalog-export/` 配下へ `works.csv`、`items.csv`、`sources.csv`、`source_targets.csv`、`crawl_runs.csv`、`artifacts.csv` の6 CSV snapshotを出力する。各CSVはtable identityとforeign keyを保持し、履歴をflat JOINで直積化しない。CSVはUTF-8 BOM、header付きで、NULLは空欄、`available` と `enabled` は `true` / `false` とする。既定pathは入力 `catalog.sqlite`、出力directory `catalog-export` であり、既存snapshotを上書きせず、CSVからCatalogへ戻す機能はない。

`catalog item-status <item_id> [pending|completed|skipped|external]` CLIはstatus省略時にItemの現状を表示し、指定時は`CatalogService`経由で状態を変更する。`catalog item-note <item_id> "text"` はnoteをset/updateし、`--clear`はnoteだけをNULLに戻す。status/note操作はCrawlRun / Artifactを作成しない。Discovery refreshはoperator-maintainedなstatus/noteを上書きしない。Batch Plannerは`pending`だけを候補にし、通常crawl成功後も既存の`mark_item_completed()`が使われる。

日時は`catalog.service.now_jst()`で生成するaware fixed-offset JST timestampを、ISO 8601の`+09:00`文字列として保存する。naive datetimeは拒否する。通常runtimeはschema v6だけをサポートし、異なるversionは暗黙migrationせず明示的に失敗する。v6では7 tablesとrequired columns、Item status CHECK、Source display-position CHECKを検証し、削除済み`items` columnsが存在しないことを確認する。`catalog/backup.py`はschema-neutralなSQLite online backup、WAL-safe standalone化、quick_check、overwrite拒否を提供する。`catalog/migrations.py`は明示`catalog migrate`用のsequential v3→v4→v5→v6 runnerを持ち、migration前automatic backup、single-transaction rollback、final validationを行う。

採用した上位flow:

```text
watchlist.yaml
    ↓
Discovery Service / Discovery Adapter
    ↓
    catalog.sqlite (works / items / sources / source_targets / crawl_runs / artifacts)
    ↓
Batch Runner / Site Policy
    ↓
Crawl Request
    ↓
既存CrawlerRunner
```

現行実装には、BookWalker quotaの実サイトlive click検証と、quotaのサーバー側実消費をCatalogだけから検証する機能は存在しない。

Watchlist CLI、Catalog Service、Work-aware Discovery framework、Crawl Request最小基盤、Schema v6 Batch Planner / Executor、Site Policy registry / Manga ONE・BookWalker Policyは実装済みである。Discoveryはtargetの`work_key`でWorkをfind/createし、`label`は新規Workのtitle初期値にだけ使う。新規recordはWork配下にItem、Source、web/default targetを原子的に作成し、既存recordはItemを再利用する。Batch PlannerはWork metadataとItem order metadataからcandidateを生成し、enabledなweb targetを`priority ASC, target.id ASC`で選ぶ。Batch Executorはstale validation後にCrawlRunを作成し、quota記録、Crawler、packaging、Artifact / Run / Itemの成功確定を順序づける。現行CrawlerRunnerへCatalog read/writeは追加せず、1 URL -> 1 run責務を維持する。

主要仕様:

- Discovery対象は明示Watchlistだけ
- Watchlist targetはstable `key` と明示的な `work_key` / `label` を持つ
- Catalog v3 Phase 5は `works / items / sources / source_targets / crawl_runs / artifacts` の6テーブルをauthorityとする
- full syncはcomplete時だけmissing sourceをunavailable化
- 現行incremental実装はlatest側から異なるknown source 2件連続で停止し、同一stable identityの重複観測はstreakに加算しない
- 採用仕様ではdefault known-streakを維持しつつ、site固有access遷移に必要なstable boundary hookを許容する。BookWalker Discoveryはこのhookを利用する
- 別site同一作品は自動mergeせずwarning only
- access modeは `owned / free / quota / paid / unknown`
- quotaは基本crawl開始時に消費記録
- site上に再閲覧猶予がある場合は `access_granted_until` で扱える。BookWalkerはsource単位grantを仮定しない採用仕様
- Batch/Site Policyが今回の `access_strategy` を解決する
- quota sourceでもactive grant中は `direct`、新規枠を使う場合だけ `quota`
- quota limit/reset ruleそのものをCrawlerへ渡さない
- Crawlerはtitle/author/order/genreをoptional inputとして受け取れるようにする
- metadataはfield単位で `explicit request > adapter > packaging fallback`
- metadata未指定なら現行Adapter自動取得を維持する
- crawl + packaging成功時だけArtifact(present)、CrawlRun(succeeded)、Item(completed)を1 transactionで確定

Phase 5AのBatch Plannerは `pending` itemだけを対象にし、completed / unavailable / paid / unknownをskipする。source priorityは期限付きfree、通常free、owned、quota、paid/unknownの順で、同順位はsource.id ASC。複数のquota-consuming candidateが新規枠を必要とする場合、quota仮予約の順序は`source.discovery_key`ごとのDiscovery groupをgroup内最小source.id（Catalog登録順）で並べ、group内を`order_key`のnatural orderで並べる。`order_key`を解釈できない場合は`order_label`、最後にitem.idのstable fallbackを使う。`discovery_key = NULL`のcandidateは明示groupの後ろに置く。free、owned、active grant中のquota sourceはdirectのままでこのquota allocation順序に入らない。Catalog metadataは`Work.title -> title`、`Work.author -> author`、`Work.genre -> genre`、`Item.order_label -> order`を従来どおり写し、positionは`archive_position_prefix(Source.display_position) -> artifact_prefix`へ分離する。positionがある場合は最小3桁のfilename prefix、NULLの場合はprefixなしとし、`order_key`やIDから補完しない。Batch Plannerはsite-scoped snapshotの全status Item/Sourceを対象に、`archive_stem()`後のsanitized base stemを同一Work内で比較し、distinct Item IDが複数のgroupだけへ`{site}-{Source.external_id}`を設定する。同一Itemの複数Sourceはcollision扱いしない。Manga ONE/Magapoke固有のsuffix workaroundは廃止した。

Manga ONE Policyはsite-wide local quotaを4枠、09:00/21:00 JSTのhalf-open window、24時間grantとして扱う。current window内の`quota_started_at`だけを数え、active grant（`access_granted_until > now`）はdirectでslotを減らさない。quota candidateはplanner内だけで仮予約し、Catalogは変更しない。手動・外部clientの実消費はCatalogから観測できない。

CLIは `batch plan --site mangaone --catalog catalog.sqlite` と `batch run --site mangaone --catalog catalog.sqlite` を提供する。`batch plan`はread-onlyで、`batch run`はcandidateをsequentialに実行し、quota stateをCrawler開始直前に保存し、crawl + packaging成功後だけcompletedを更新する。`--limit N`は先頭N件に制限し、失敗時は後続を実行しない。

BookWalker Discoveryはseries listから商品URLを列挙し、商品ページのreader controlを観測してCatalogへ反映する。BookWalker Site Policyはsite-wide 1 quota / 05:00 JST half-open windowを評価し、`access_granted_until`をdirect判定に使わない。Batch Executorはquota candidateの`quota_started_at`をCrawler開始前に保存し、`access_granted_until=NULL`を許容する。同一window内の失敗はrefundせず、Executorの現在Catalog再検証で同一candidateをCrawlerへ再投入しない。Manga ONEの24時間grant挙動は維持する。実サイトquota clickは自動検証していない。

誤ったlogout状態のBatch実行などで、実際のreader消費ではなくCatalog上の予約だけを戻す必要がある場合は、`scripts/restore_bookwalker_quota.py`を使う。既定はdry-runで、`--crawl-run-id`（failedかつquotaのCrawlRun）または`--source-id` / `--external-id`を指定し、`--apply`時には先にverified SQLite backupを作る。修復対象は`quota_started_at`と`access_granted_until`だけで、`access_mode`、CrawlRun、Item status、Artifactは変更しない。これはBookWalkerサーバー側の10分利用を巻き戻す機能ではない。executor実行中の同時修復は避ける。

### 22.3 Discovery framework（実装済み）

#### Current incremental known-streak threshold

The current generic incremental Discovery implementation stops after five
consecutive distinct known source identities. Observing a new source resets
the streak to zero. Any older two-known-source examples in this historical
note describe the former default and are superseded by the current value.

#### P2 Discovery position assignment

`DiscoveryService` retains the first-observed Source IDs in Adapter yield order
as a run-local ordered set. The Adapter remains responsible for canonical
newest-to-oldest Discovery order. A bounded-capable Adapter also attaches a
run-local `global_display_position` hint after observing the complete listing
and before applying its scope slice. The hint is not persisted separately.

`Source.display_position` means the 1-based position in the site's complete
work listing ordered oldest-to-newest. It is never inferred from episode
labels, numeric IDs, `order_key`, `order_label`, or publication dates. Bounded
Discovery filters synchronized Sources but does not renumber them: if the
complete listing positions selected are 4..7, Catalog receives 4, 5, 6, 7.
The Service validates hints (`int`, not `bool`, and `>=1`), rejects conflicting
Source/position mappings, and finalizes them only after safe completion.

Unbounded full Discovery retains the existing reverse of the canonical stream
to assign `oldest=1 ... newest=N`. Bounded full Discovery requires a global hint
for every observed Source and fails closed without one; it never falls back to
scope-local `1..N`. Incremental Discovery uses an available global hint as the
authority. When an unbounded incremental run has no hints, its existing
observed-position baseline plus append algorithm remains in force. Incomplete
runs never finalize positions or rewrite established positions; newly created
Sources may remain NULL.

Position finalization uses only records already yielded by the existing
Discovery run; it adds no pagination, DOM, HTTP, or full-list access. Discovery
position updates do not modify Item status, `completed_at`, or operator notes.

#### Magapoke M3b Batch boundary

Magapoke Policy allows free sources with `direct`. A quota source is eligible
only when Discovery observed a future `access_granted_until`, in which case it
uses `direct`, `reason="active_rental"`, and `consumes_quota=False`; all other
quota, paid, unknown, and unverified owned sources are skipped. Discovery reads
the renting countdown only within the matching episode row. The displayed
`あとNN時間` is floored human text, so the recorded `access_granted_until` is
an observation-time lower bound, not an exact rental expiry. A later non-NULL
observation refreshes that field; NULL preserves the stored grant. Discovery
does not write `quota_started_at`. There is no schema change, quota capacity,
ticket consumption, or site-specific Planner/Executor behavior. Adapter entry
remains `auto`/`direct`; quota entry remains rejected.

`DiscoveryService`（`src/screenshot_crawler/discovery/`）は、呼び出し元が用意したPlaywright Page、enabledな`WatchlistTarget`、`full`または`incremental` modeを受け取る。Chrome launch、CDP endpoint、profile、Browser Session lifecycleはServiceやDiscovery Adapterに持たせない。targetの`work_key`でWorkをfind/createし、Work titleは新規作成時だけ`label`から初期化する。author/genreは観測値が非NULLでWork側がNULLの場合だけ補完し、既存値を上書きしない。

`DiscoveryAdapter.iter_records()`はsite-neutralな`DiscoveredRecord`を順次yieldする。AdapterはCatalogを知らず、`site`と`discovery_key`はServiceがtargetからCatalogへ注入する。現行のreal-site用AdapterはManga ONE、BookWalker、Magapoke、Piccomaである。Piccomaは作品のepisode listingからDiscoveryするが、viewer / Batch / captureは未実装。BookWalkerはWatchlistのseries list targetだけを対象にする。

Discovery Serviceは各recordについて、canonical titleをItemへ保存せず、kind/orderをItemへ、title/author/genreをWorkへ反映する。新規recordではItem/Source/web-default targetを一つのtransactionで作成し、既存sourceでは既存Itemを再利用して外部状態と非NULL Item metadataだけを更新する。観測した`DiscoveredSource.url`は`SourceTargetInput(backend="web", target_key="default", locator=...)`として同じsourceへupsertする。URL変更は同じ`(source_id, web, default)` targetのlocator更新になり、既存androidやweb/direct等の別targetは変更しない。sourceのfull-sync missing reconciliationは`available=false`だけを更新し、targetの削除や自動disableは行わない。既存sourceの`discovery_key` scope不一致、または既存Itemが別Workに属する場合はincompleteとして扱い、reparentや部分的な新規graph作成を行わない。

Discovery開始時、Serviceは対象siteの既存sourceからCatalog非依存の
`DiscoverySourceSnapshot`を一度だけ作成し、adapter hookへ渡す。このsnapshotはrun開始時点をauthorityとし、run中に新規upsertされたsourceを既存sourceとして扱わない。
`DiscoveryAdapter.reconcile_access_mode()`は観測したaccess modeだけをsite-specificに調整でき、defaultは観測値をそのまま返す。`incremental_stop_decision()`は
`DEFAULT` / `CONTINUE` / `STOP`を返し、defaultでは従来のknown source 2件連続停止を使う。`STOP`はrecordのupsert後に`stable_boundary`で終了し、full modeではstop hookを呼ばない。両hookからの`DiscoveryIncompleteError`は既存のincomplete semanticsに従う。

fullはiteratorの正常終了だけを`complete=true`とし、`DiscoveryIncompleteError`または予期しない例外ではmissing sourceのreconciliationを行わない。complete fullだけが同じ`site + discovery_key` scopeの未観測sourceを`available=false`にする。現行incrementalのknown判定と2件連続streakはServiceが管理し、2件目をrefreshしてから停止する。未観測sourceはunavailableにしない。

BookWalkerはこのextension pointを実装し、run開始時点でowned/quotaだったsourceをstable boundaryとして扱う。既存owned/quotaのaccess stateは、商品ページの観測がpaid/unknownへ揺れた場合も保持する。Manga ONEはhookをoverrideせず、従来のknown-streak挙動を使う。

### 22.4 Discovery CLIの複数target同期（実装済み）

`discover` は `--key KEY`、`--site SITE`、`--all` のmutually exclusive required
groupを持つ。`--key` は従来どおり1 targetを処理する。`--site SITE` は
`WatchlistService.list_targets()` のfile orderから `target.enabled is True` かつ
`target.site == SITE` のtargetだけを選び、site名のalias変換は行わない。`--all` は
enabled target全件を同じ順番で選ぶ。disabled targetはDiscoveryServiceへ渡さない
ため、Catalogの既存stateは変更されない。`--all` の0件は
`No enabled watchlist targets.`、`--site` の0件は site名を含むメッセージを出して、
どちらも接続・Catalog初期化なしで正常終了する。

`--site` と `--all` ではtargetごとにendpointを解決し、`BrowserSession.connect()`、new Page、
既存`DiscoveryService.discover(page, target, mode)`、Page close、disconnectを
順番に行う。site-specific endpoint、global endpoint、defaultの既存優先順位と、
明示`--cdp-endpoint`の最優先を維持する。Crawler Chromeは自動起動しない。

各targetの結果（observed/new/known/complete/stopped_reason/warnings）とstatusを
表示し、失敗しても後続targetを続行する。例外failureに加えて
`DiscoveryResult.stopped_reason == "incomplete"`もtarget failureとして扱い、
`Discovery incomplete`を表示する。全target後にsummaryを表示し、`--site` ではsiteも
表示する。1件以上の失敗は`DiscoveryAllError`からCLI non-zeroへ変換する。全成功と
enabled target 0件は正常終了する。`--site --keep-open` と `--all --keep-open`は
target単位で接続を閉じるlifecycleのためCLI validationで拒否し、従来の
`--key --keep-open`だけを維持する。

cross-site duplicateは同じWork内の別Itemについて、kind/orderが一致する場合だけ候補をwarningにする。warningはmerge、reparent、delete、completed化を行わない。

### 22.5 Batch Planner / Executor（Schema v3 Phase 3実装済み）

`BatchPlanner`（`src/screenshot_crawler/batch/planner.py`）はWork-aware read snapshotから
candidateを生成する。metadataは`Work.title` / `Work.author` / `Work.genre` / `Item.order_label`
から作り、Itemのorder fallbackは`order_key`、`order_label`、`item_title`、`item.id`の順である。
指定siteのSourceを持つItemだけを対象にし、Web targetだけを`priority ASC, target.id ASC`
で選ぶ。`BatchCandidate`には`backend` / `target_key` / `locator`をsnapshotする。

`BatchExecutor`（`src/screenshot_crawler/batch/executor.py`）はcandidateを1件ずつ既存
`CrawlerRunner`へ渡す。`CrawlerRunner`はCatalogを知らず、Batch側だけが`item_id` /
`source_id` / `target_id`とCatalog stateを扱う。

実行前にitemが`pending`であり、sourceのitem/site/access_mode/availableとtargetの
source/backend/target_key/locator/enabledがcandidateと一致することを確認する。backendはwebだけを
受け付ける。Policyのaccess decisionも再確認し、stale candidateはCrawlerを呼ばずに停止する。

Candidateから次の`RunConfig`を作る:

```text
site / source_url / access_strategy / output_metadata
output_dir = output/batch/<site>/item-<item>-source-<source>-<JST timestamp>-<uuid>
diagnostics_dir = <run directory>/diagnostics
```

実行はsequential、stop-on-first-failureである。candidate validation後、Crawler開始前に
`CrawlRun(running)`を作成する。quota candidateだけはその後に`record_quota_access()`を呼び、
Policyの`access_grant_until()`で計算したgrantを保存する。direct candidateはquota stateを
変更しない。保存後にcrawl、viewer、packagingが失敗してもquota stateはrefundしない。

Crawlerが`END`または`NEXT_CONTENT`で正常終了し、既存`package_crawl_output()`が成功した後、
archiveの存在を確認してSHA-256 / byte sizeを計算する。Catalogのnarrow helperがArtifact(present)、
CrawlRun(succeeded)、Item(completed)を1 transactionで確定する。Catalog更新失敗時も生成済みarchiveと
status sidecarは削除しない。Crawler、異常停止、packaging、archive検証、finalizeの失敗は
CrawlRun(failed)へ記録し、Itemはpending、Artifactは作成しない。

実行CLI:

```powershell
.\.venv\Scripts\python.exe -m screenshot_crawler.cli batch run `
  --site mangaone --catalog catalog.sqlite `
  --output-root output\batch --library-dir output\Books --limit 1
```

`batch plan`は引き続きCatalog read-onlyであり、`batch run`だけがquota local stateと
CrawlRun / Artifact / Item statusを書き換える。Manga ONEとBookWalkerのquota policyは既存挙動を
維持し、Android targetはCatalogへ保持できるがPhase 3 Executorでは実行しない。


### Catalog v6 / Magapoke M3c1 current update

Catalog schema v4 adds nullable sources.published_at and explicitly migrates v3 after an automatic pre-migration backup inside the existing transactional catalog migrate flow. Ordinary initialization remains non-migrating. Timestamp validation uses the same aware ISO/JST normalization as other Catalog timestamps.

Discovery passes DiscoveredSource.published_at into SourceInput; a non-NULL observation updates the Source, while NULL preserves the prior value. Magapoke parses the live-confirmed YYYY/MM/DD row date to JST midnight. This represents the site-observed publication day normalized for stable ordering, not an observed time of day. order_key remains site-neutral and Magapoke keeps it NULL.

Batch metadata now carries generic quota resource, scope, limit, and commit timing. Work-scoped quota limits are applied by grouping on Work.id; sources are ranked by published_at ascending with NULL last, then existing item ordering and stable source ID. Only work-scoped policies use the direct-first phase; Manga ONE and BookWalker retain their established site quota ordering. BatchExecutor passes quota_resource through RunConfig and commits after-observed consumption only when the Adapter reports a matching aware timestamp.

### Phase 4 current state: generic grant-only

Generic grant-only uses the existing adapter entry path with Core
`entry_only=True`. Work Ticket state is persisted in Catalog schema v6 as
Work/site/resource state, and confirmed consumption atomically updates that
state plus the source grant. Local cooldown skips happen before browser/page
creation; confirmed grant-only runs do not capture, package, or complete the
Item. Premium Ticket grant-only and policy-ordered `all` are implemented in
Phase 5; Premium balance remains live-only and is not stored in Catalog.
Normal Batch and grant-only share the observed resource-consumption persistence
helper; confirmed Work Ticket consumption updates source grant and Work state,
and later failure does not undo either update.
This Phase 4 section is the current implementation state and supersedes the
older Phase 3 planning sentence below.

### Phase 5 current state: Magapoke Premium Ticket and generic all

Magapoke exposes `work_ticket` then `premium_ticket` through the generic
grant-only contract. `--grant-only premium_ticket` uses the normal
`entry_only=True` Adapter path, reads the live semantic Premium Ticket balance,
respects Work Ticket priority, and fails closed on ambiguous UI. A clear zero
returns `premium_ticket_exhausted` and stops only that resource pass. Confirmed
Premium consumption persists the source grant through the Policy's conservative
71-hour `access_grant_until`; no Premium balance or Work-scoped resource state
is stored. `--grant-only all` replans Catalog between Policy-ordered passes,
shares its total site-attempt `--limit`, applies cross-pass pacing, and stops
the whole run for candidate site-operation errors or fatal AccessGuard errors.
Expected cooldown/resource-unavailable outcomes remain pass-local skips.
Grant-only leaves Items pending and creates no capture/package/Artifact.

### Phase 6 cross-site verification current state

The full automated regression suite has been run and is green across Magapoke,
Manga ONE, and BookWalker. It covers Phase 1 pacing and timeout isolation,
Phase 2 AccessGuard/metrics, generic resource passes, Work/Premium grant-only,
Catalog v6 migration, adapter retry/capture, and normal Batch semantics.
Read-only `batch plan` also passed for all three sites on a temporary v5 -> v6
Catalog migration copy. Actual normal live Batch and scarce Work/Premium
consumption were not forced because no safe non-consuming candidate/session was
available. The detailed matrix is `docs/PHASE6_VERIFICATION.md`; current status
is **AUTOMATED VERIFIED / LIVE PARTIAL**.

### Batch candidate failure and interruption current state

Batch site-operation errors are represented as candidate-scoped failures and
stop the sequential Batch after the current candidate is cleaned up. The
original underlying error type and message remain in the CrawlRun and metrics.
Expected cooldown/resource-unavailable outcomes continue as skips. AccessGuard
stops and Catalog/configuration errors remain Batch-fatal.

Operator cancellation is normalized to `BatchInterruptedError` with
`stop_reason=interrupted`. The active candidate is failed, no later candidate
starts, and the CLI exits with code 130. Confirmed resource consumption is
persisted before interruption is recorded; unconfirmed consumption is not
inferred. Page, AccessGuard, and browser cleanup are bounded best-effort.
Candidate failure metrics also carry `error_type` and `error_message`. The
entry-only runner reports missing confirmed consumption as
`AccessConsumptionUnconfirmedError` instead of a generic `LookupError`.
Adapters may override `initialize_entry_only()` when grant-only access
confirmation must not perform full crawl readiness or capture setup. Cleanup
of AccessGuard, page, and BrowserSession is bounded and never replaces an
active candidate error; interruption is preserved only when no primary error
is already in flight.

### Phase 1 runtime settings / pacing

rootの`crawler.yaml`は`runtime_settings.py`が読み込み、`SiteRuntimeSettings`へresolveする。
ファイルまたはsite entryがない場合は`page_turn_delay_ms=1000`、`inter_candidate_delay_ms=3000`を使う。
不正なdelay（負数、bool、文字列、float）は明示的に失敗し、0はoperator overrideとして有効である。
CrawlerRunnerはYAMLを読まず、CLI/Batchがresolved値を`RunConfig`またはBatch orchestrationへ渡す。

正常なCONTENT captureでは、logical page/spreadの全artifactをsaveした後にmanifest/progressを一括persistし、
`page_turn_delay_ms`を1回だけ待ってからinitial `adapter.go_next()`、`adapter.wait_for_change()`を呼ぶ。
delayはadapter timeout/grace/retry budgetの外側で、AD、loading polling、same-content wait、entry clickには適用しない。
BatchはsiteへアクセスしたcandidateのPageをcloseした後、次のsite-accessing candidateの前に
`inter_candidate_delay_ms`を1回だけ適用し、末尾candidateやCatalog local skipには適用しない。

Magapoke BatchはDiscoveryのlatest-firstを維持し、同一Work内を`published_at ASC (NULL last), source_id DESC`
で処理する。Jump+もDiscoveryのlatest-firstを維持し、同じWork内orderingを通常direct candidateへ適用する。
既存のdirect先行とWork間orderingは維持する。AccessGuard、403/429 stop、challenge/CAPTCHA、
Phase 2のAccessGuardは3site共通で接続済みで、relevant hostの403/429、明示challenge、visible
CAPTCHAをdistinct stop reasonとして扱う。Batchのbody-free access metricsは`output/metrics/*.jsonl`
へ逐次flushされ、fatal stop前のCatalog更新とmetricsを保持する。fatal access stop後は、
CONTENTのpacing後およびAD advancement前に再確認し、新しいintentional `go_next()`を開始しない。
Phase 3では、Site Policyがgeneric access resourceのsupported/order contractを提供し、
Plannerがexplicit `quota_resource`を検証する。Batchはnormal/default pass後にPolicy順でreplanし、
requested resource以外へのsilent fallbackをしない。Phase 4/5では同じcontractをgrant-onlyにも使い、
Work Ticket cooldown、Premium live balance、Policy順`all`を実装している。

### Capture dedupe semantics (current)

Capture fingerprints are artifact evidence, not global logical-page identity.
The runner now deduplicates a captured part only when all of these match:

```text
ContentIdentity
spread part count
spread part index
capture fingerprint
```

This preserves distinct logical pages that happen to have identical encoded
bytes, and preserves both parts when a spread uses the same bytes on both
sides. A repeated capture with the same logical identity, part structure, and
fingerprints remains subject to the existing `max_same_content` guard.

The change is generic Core behavior; it is not a Zeblack-specific exception.
The persisted manifest continues to record the logical identity, part metadata,
and per-artifact capture fingerprint.

### Site-native bounded Discovery（B6 Jump+ / Z4-1 Zeblack implemented）

正式仕様は `docs/BOUNDED_DISCOVERY.md`。現在のB6実装状況は次のとおり。

- Watchlistの`DiscoveryScope(from_url / through_url)` model、YAML parse、mapping / boundary存在 / non-empty string validation: **IMPLEMENTED**
- scope付きtargetのenable / disable等のWatchlist rewrite preservation: **IMPLEMENTED**
- scopeなしtargetの既存load / rewrite互換: **IMPLEMENTED**。scopeなしtargetは従来どおりunboundedとして扱い、scope専用CLI optionは追加していない
- common Discovery capability gate: **IMPLEMENTED**。`DiscoveryAdapter.supports_bounded_discovery` のdefaultは`False`で、明示的にopt-inしたAdapterだけboundedを受け付ける。Magapoke / BookWalker / Manga ONE / Jump+ / Zeblack / Piccomaはopt-in済みで、その他の未対応Adapterはdefault `False`のまま
- scope付きtargetを未対応Adapterへ渡した場合: **IMPLEMENTED**。Work作成前にincompleteとして停止し、`iter_records()`、unbounded fallback、Item / Source / SourceTarget同期を行わない
- bounded full: **IMPLEMENTED**。対応Adapterがyieldしたrecordは通常どおり同期し、正常終了時は`complete=True` / `stopped_reason="exhausted"`とする。global missing-source reconciliationは実行しない。完全一覧を把握できるAdapterはscope slice前にglobal display-position hintを付与し、scope-local `1..N`へ再採番しない。hintなしbounded runはincompleteでfail closedとする
- bounded incremental common semantics: **IMPLEMENTED**。generic known-streak（5件の連続distinct known identity）と`incremental_stop_decision()`のstop hookをscopeなしと同じ順序・契約で適用する。global hintがあればそれをauthorityとして使い、boundedでhintがなければincompleteとする
- Magapoke bounded Discovery: **IMPLEMENTED**。既存strict parserで`title_id` / `episode_id`を検証し、parse済みlatest-first listing order上でglobal positionを計算してからfrom-only / through-only / both / singletonのinclusive rangeを選択する。invalid / foreign / different-title / missing / reversed boundaryはyield前にincompleteとする
- Magapokeのboundary validation前yield防止: **IMPLEMENTED**。既存の全listing parse・buffer構造の後にrange確定してからyieldするため、invalid scopeでCatalog partial writeを行わない
- BookWalker bounded Discovery: **IMPLEMENTED**。strict `/deUUID/` parserでproduct UUIDをboundary identityとし、full collected series-list membershipと既存のcollect order上でglobal positionを計算してからfrom-only / through-only / both / singletonのinclusive rangeを選択する。invalid / foreign / missing / reversed boundaryはproduct observation前にincompleteとする
- BookWalkerのfirst-volume inference: **IMPLEMENTED**。scope slice前にfull productsで候補を算出するため、bounded sliceの外側にある後続巻を文脈として維持する
- Manga ONE bounded Discovery: **IMPLEMENTED**。strict HTTPS / `manga-one.com` chapter parserで`work_id` / `chapter_id`をboundary identityとし、complete listingのglobal positionを計算してから既存のlisting order上でfrom-only / through-only / both / singletonのinclusive rangeを選択する。relative hrefはpage URLとの`urljoin()`後にparseし、foreign hostはrejectする
- Manga ONEのbounded buffering: **IMPLEMENTED**。scopeなしは既存のpage/card単位streamingとpartial-refreshを維持し、scope付きだけ全listingをbufferしてpagination完了・boundary validation後にyieldする。invalid / foreign / different-work / missing / reversed boundaryやbounded pagination failureではCatalog partial writeを行わない
- Jump+ bounded Discovery: **IMPLEMENTED**。既存のstrict episode URL parserで`episode_id`をboundary identityとし、全rangeのpagination・duplicate・network scope・total validationを完了した`records_by_id`のcanonical insertion order上でglobal positionを計算してからfrom-only / through-only / both / singletonのinclusive rangeを選択する。latest-first ordering、range direction、row directionは変更しない。invalid / foreign / missing / reversed boundaryはyield前にincompleteとする
- Jump+ bounded buffering: **IMPLEMENTED**。scope付きfull / incrementalとも全rangeをbufferしてからboundary sliceをyieldし、後続range失敗時にpartial recordをyieldしない。scopeなしincrementalの既存streamingとscopeなしfullの既存全件bufferは維持する
- Jump+ / bounded cross-site no-merge regression: **IMPLEMENTED**。bounded対応Fakeを使った共通回帰で、同じ`work_key`でもsiteをまたぐItem自動mergeを行わないことを確認している
- Zeblack production Adapter bounded support: **IMPLEMENTED**。strict chapter-list / viewer parser、DOM/protobuf exact-set validation、latest-first canonical order、raw DOM oldest-first index由来のglobal position、chapter_id boundary slice、およびyield前bufferingを`ZeblackDiscoveryAdapter`で実装済み。Z4-1時点ではDiscovery registryのみ登録し、Z5でBatch Policy registryにも登録した
- Piccoma bounded Discovery: **IMPLEMENTED**。canonical viewer URLからproduct / episode identityを厳密にparseし、完全なproduct listingをbuffer・検証してからlatest-first順のinclusive rangeを選択する。global display positionはoldest-first native DOM index + 1でslice前に付与し、status wrapperとdescendantsにある`PCM-epList_status_*` marker集合が`PCM-epList_status_free`のみ、かつexact `¥0`の場合に限りfreeとする。Viewer accessの再確認、Viewer / Batch / captureは未実装
- 他siteのbounded range boundary parse / same-scope validation / canonical range extraction: **NOT YET IMPLEMENTED**

The following historical summary predates Z4-1; the current production
bounded adapters include both Jump+ and Zeblack. Site Policy and Batch
changes remain outside the Zeblack Discovery phase.

### Archive health check and recrawl preparation (implemented)

`scripts/prepare_recrawl.py` inspects only `completed` Catalog Items in an
exact `--site` and/or Work title scope. It does not run Discovery or modify
sources, source targets, crawl runs, or ZIP contents. The current site policy
mapping is intentionally limited to the confirmed production capture paths:
Comic DAYS and Magapoke prefer JPEG (`.jpg`/`.jpeg`) with PNG fallback, while
MANGA ONE prefers source-native WebP with PNG fallback. An explicitly unknown
site fails closed; work-only scans skip sources whose policy is undefined.

ZIP page members are inspected at archive root with case-insensitive
extensions. `PREFERRED_ONLY`, `FALLBACK_INCLUDED`, `UNEXPECTED_FORMAT`,
`BROKEN`, `MISSING`, and `AMBIGUOUS_ARTIFACT` are reported using site-neutral
classifications. Default output lists only problems; `--show-all` also lists
preferred items. `--ignore-missing` keeps MISSING in the classification
summary but excludes it from problems, recrawl candidates, and apply changes;
with `--show-all` it is printed as `MISSING (ignored)`.

The default is dry-run. With `--apply`, fallback/unexpected/broken archives
are moved to `output/reimport-backup/<timestamp>/` while preserving their
relative path under `output/Books` where possible, then their Catalog locator
is updated and the Item is returned to `pending`. Missing artifacts retain
their locator, are marked `missing`, and then return to `pending`. Ambiguous
artifacts and ignored missing artifacts are never mutated. Move, artifact, and
pending failures are reported as partial failures without a rollback
framework. Synthetic ZIP coverage is in
`tests/unit/test_prepare_recrawl.py`; no real Catalog `--apply` run is part of
the implementation verification.

B1/B2/B3/B4/B5/B6ではtitle、order、episode number、漢数字変換、cross-site fuzzy matchをscope判定に使わない。Catalog schema、Batch Planner / Executor、CrawlerRunner、BookWalker、Magapoke、Manga ONE以外ではJump+だけproduction bounded Discoveryを実装している。bounded scope内recordは通常のItem / Sourceとして同期するが、cross-site Itemのautomatic mergeやcompleted伝播は行わず、重複crawlは安全側の挙動として許容する。

将来cross-site dedupeが必要になった場合はphysical Item mergeより先にhuman approval付きnon-destructive equivalence mappingを検討する。physical mergeは現計画の対象外である。
