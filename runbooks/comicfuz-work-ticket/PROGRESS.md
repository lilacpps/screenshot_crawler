# ComicFUZ `work_ticket` — PROGRESS

**Status:** Phase 01 complete; Phase 02 PASS; Phase 03 native-contract research in progress
**Runbook authored:** 2026-11-23 JST
**Execution contract:** [README.md](README.md)
**Implementation branch:** `feat/comicfuz-work-ticket`（`main` HEAD `589d375502d3ec6465f782302122d1eec346cf3a` から作成）
**Worktree baseline:** 専用worktree `worktree-a`、開始時clean。元の `feat/herosweb-free` の未コミット差分は引き継いでいない。
**Runbook baseline:** 2026-11-23 の `main` 現行コードを確認して作成。実装開始時のHEADは上記。

## 既知の事実・ユーザー指定

- ComicFUZ の作品チケット（チャージ）は **毎日午前0時 JSTに回復**（ユーザー確認）。経過23時間ではない。
- 消費は作品ごと1枚。Premium Ticket、コイン、メダル、有料操作は実装しない。
- 話一覧の「無料」は`free`、コインマークは`paid`、何も表示されない正規行は`quota`候補。
- Phase 02ではDiscoveryが可視の正規行を`free` / `paid` / `quota`へ分類し、Policyは`work_ticket`のみをwork単位で候補化する。Adapterのticket entryはPhase 03で実装する。
- shared Catalog `quota_resource_states` と site-neutral optional unresolved-work guardを使い、DB schemaは変更していない。
- 話選択後の「チャージで読む」が消費操作であることはユーザー確認済み。正の消費response/consumed timestampとgrant期限のnative contractは**未観測**であり、固定期限を推定しない。

## Phase checklist

| Phase | Status | Exit evidence |
| --- | --- | --- |
| 01 Read-only DOM/native 調査と仕様確定 | PASS | 5作品を調査。匿名とログイン済みwork 3667の分類一致を確認。消費response/expiryは後続Probeへ |
| 02 Discovery/Policy/日次skip | PASS; independently reviewed | JST 00:00境界、work分離、request/page 0、work履歴guard、影響回帰。独立レビュー BLOCKING=0 |
| 03 Adapter/通常Batch/grant-only | IN PROGRESS — native-contract research | 消費click前にhandler/positive proof/consumed time/grant expiryを確認。live consumeはsynthetic/review Gate03後 |
| 04 実サイト・独立検証 | TODO | 変更SHA、限定E2E、DB/ZIP/requests監査、レビュー、残リスク |

## 実装着手時に記入する項目

- `main` HEAD SHA / 専用worktree / 未コミット差分:
- Phase01に使った作品URL・chapter ID（公開IDのみ）とログイン/匿名差:
- 観測したDOM/first-partyフィールド名と条件（秘密・本文・署名URLを保存しない）:
- チケット消費操作が navigation / button / その他のどれか:
- 事前の副作用なし判定、消費の正の証拠、時刻の根拠:
- 閲覧grantの正確な終了時刻または安全な観測下限:
- 00:00 JST反映遅延・日跨ぎ時の扱い:
- 変更ファイル/commit SHA:
- Unit/browser/CLI/inventory regression の実行コマンドと結果:
- 実サイトで消費したチケット（作品ID、話ID、JST時刻、枚数、事前許可）:
- grant-onlyと通常BatchのDB監査、同Pageの証拠、ZIP/CRC/Manifest監査:
- 独立レビュー（blocking数）、残課題、Done/Live pending判定:

## 決定事項と変更時の扱い

**Decision 001:** Work resource stateは既存 `site,work_id,resource` キーと `last_consumed_at` を利用。ComicFUZ SitePolicyだけが「最終消費日の翌日00:00 JST」を算出する。他サイトの経過時間ルールは維持。変更する場合は根拠と回帰テストを残す。

**Decision 002:** 「無表示=quota」は**描画済み・完全照合済み・未知の価格/権利マーカーなし**に限る。隠れたコイン、遅延hydrate、未判定のアイコン/ラベルがある場合はfail closed。

**Decision 003:** 無料directの既存厳密preflightとJPEG/END/ZIP処理は維持。quota/有効grantは対象話直行の最小変更を検討し、別話へのfallbackやpremium/coin消費を禁止。

**Decision 004:** 実サイトの不可逆なチケット消費を伴うE2Eは、synthetic検証後、ユーザーから枚数上限を含む明示許可がある場合にのみ実施。許可を得られなければlive pendingと明記し、synthetic verifiedをDONEと偽らない。

## Phase 01 — Read-only listing and entry observations (2026-11-24)

**Gate:** Explorer conditional PASS、BLOCKING=0。匿名/ログイン分類一致の条件はPhase 02前半で解消した。Phase 01は実チケットを使わず完了した。残るPhase 03条件: (1) `pointConsumption` をDiscovery access mode判定へ使わない、(2) 実際の「チャージで読む」操作はPhase 03 synthetic gate後まで行わない、(3) 正の消費証拠・消費日時・閲覧期限は実消費前にnative contractを調べ、未観測の固定72時間を実装しない。

### Repository and browser setup

- Dedicated branch starts from `main` `589d375502d3ec6465f782302122d1eec346cf3a`; worktree was clean when created. No prior-worktree uncommitted changes were copied or changed.
- The only current ComicFUZ listing classifier treats exactly one visible row-local `p[class*="Chapter_chapter__price_free__"]` with text `無料` as `free`; any row without that proof currently remains `unknown`. `ComicFuzSitePolicy` admits `free` and `direct` only. Quota, grant-only, and resource state are not implemented.
- Attached to the existing shared crawler browser using `BrowserSession.connect("http://127.0.0.1:9222")`; no Chrome was launched. Created and closed a temporary Playwright Page in the existing context. A pre-navigation snapshot showed one existing context/page and no ComicFUZ tab. All live inspection was limited to the five user-provided `/manga/<workId>` list pages; no reader route was opened.

### Live listing evidence

All five work pages returned HTTP 200. On each page the flattened first-party `#__NEXT_DATA__` chapter count equaled the number of rendered chapter headings. The row-local observations were:

| Work | Native / DOM rows | Visible `無料` | S/G price marker | Regular blank rows | Other observation |
| --- | ---: | ---: | --- | ---: | --- |
| 3667 | 25 / 25 | 1 | chapter 76633: S + G | 23 | `チャージ完了!` banner visible |
| 3152 | 93 / 93 | 9 | none observed | 84 | `チャージ完了!` banner visible |
| 3342 | 21 / 21 | 5 | chapter 49008: G only | 15 | `チャージ完了!` banner visible |
| 3500 | 118 / 118 | 5 | chapter 82165: S + G | 112 | `チャージ完了!` banner visible |
| 3315 | 127 / 127 | 1 | G only observed (46 rows) | 80 | `チャージ完了!` banner visible |

- Free proof is a visible exact-text `p.Chapter_chapter__price_free__*` row marker. Price evidence is within the same row's visible price region: image alt `シルバーメダル` with public static asset `/assets/manga_detail/silver.svg`, and/or `ゴールドメダル` with `/assets/manga_detail/gold.svg`. One observed row had both; other observed rows had G only. The common `img.Chapter_chapter__price_gold__*` class alone is not sufficient for classification; Phase 02 must match the recognized alt and static asset inside the visible price region.
- A regular blank row had no visible price-region element and no free marker. Existing row thumbnails and comment/like icons are present, so row-wide icon absence is not a valid rule. Hydration/loading, unknown or hidden price controls, malformed/ambiguous rows, and conflicting marker combinations remain fail-closed.
- The current first-party chapter object includes `badge` and `pointConsumption`; on work 3667, an S+G-marked row had `badge=2` and `pointConsumption={type:1, amount:60}`, while a visually blank row had `badge=1` and `pointConsumption={amount:30}`. The free row had no badge and an empty pointConsumption object. These values do not match the user-confirmed visual classification, so they are recorded as unknown semantics and must not be used as `free`/`quota`/`paid` proof.
- Each sampled work showed visible `p.Charge_charge__text__*` exact text `チャージ完了!` (ASCII `!`) and an image with alt `チャージ`, static asset `/assets/manga_detail/charged.svg`. An earlier false result used a full-width exclamation and was corrected. In work 3667, pageProps had `manga`, `chapters`, and other public fields but no charge/ticket/access key among inspected keys through depth 3; no status is inferred from uninspected server state.
- Anonymous parity probe: with the same existing CDP browser, a disposable `new_context()` without shared cookies/storage and the logged-in shared context both produced 25 work 3667 rows with identical adapter classifications: `free=1`, `paid=1`, `quota=23`. The anonymous context showed sign-in and no mypage link; the logged-in context showed mypage. No cookies/storage values were read or recorded, no episode was clicked, and no reader/resource action occurred.

### Modal and consumption boundary

- Work 3667 blank-row chapter 76630 was selected once after the user confirmed that selecting an episode opens a non-consuming modal and the consume action is the modal's `チャージで読む` button. The route stayed `/manga/3667`, one visible dialog appeared with `チャージで読む`, `コメント一覧へ`, and `キャンセル`, and the observed post-selection ComicFUZ requests were CSS GET only; no ComicFUZ fetch/XHR occurred. Analytics and unrelated browser resources are excluded from this conclusion.
- `チャージで読む` was not clicked. No `useTicket`/consumption response, server-side consumed timestamp, work-ticket reset timestamp, grant expiry, or post-charge viewer state was observed. The confirmed UI has a single charge action, but its request and positive-consumption proof still require code/native observation before Phase 03 live use. No real ticket was consumed.
- Daily reset at 00:00 JST is user-confirmed. No native UI reset date or 23-hour countdown was observed; implementation and boundary tests will follow the user authority and synthetic clocks.

### Baseline tests

- PASS: `.venv/Scripts/python.exe -m pytest -q --basetemp=.tmp/pytest-comicfuz-phase01-baseline-unit tests/unit/test_comicfuz_discovery.py tests/unit/test_comicfuz_policy.py tests/unit/test_comicfuz_adapter.py` — 32 passed, 0 skipped. Existing pytest-asyncio deprecation warnings.
- PASS: `.venv/Scripts/python.exe -m pytest -q -x --basetemp=.tmp/pytest-comicfuz-phase01-baseline-integration-one tests/integration/test_comicfuz_discovery_browser.py` — 16 passed, 0 skipped. Browser-backed baseline.
- INCOMPLETE: the full adapter browser module was not completed in one invocation. A combined run passed 88 cases then stopped producing output and was interrupted; a separate 14-case tail passed, and route-drift passed alone. The initial long temporary path issue was resolved by using short `%TEMP%/cfz...` basetemp paths. Do not count the combined module as a full pass; repeat in bounded groups in Phase 04 if needed.
- Not run: full `pytest -q`, live charge, and inventory UI verification. No production code changed during Phase 01.

### Phase 02 approved scope

Use visible row-local proof for `free` / `paid` / regular blank `quota`; keep hidden or unknown state fail-closed and preserve the full existing identity/order/scope contract. Add ComicFUZ work-scoped `work_ticket` eligibility and JST next-midnight local gating, with cooldown settings ignored. The Explorer also identified that current unresolved-attempt observation is a metrics sink and run-history guards are source-scoped. A small site-neutral optional work-scope unresolved-attempt hook may be needed to block a second episode on the same work when the first attempt's consumption is unknown; it must be default-empty, must distinguish positive persisted consumption from unknown, and must have no request/page for local skips. Any shared change is limited to this guard and inventory retry-time presentation, with corresponding shared docs/note and broad affected tests. Existing quota/source grant windows stay episode-scoped and independent from the work daily reset.

## Phase 02 — Discovery / SitePolicy / daily skip (PASS; independently reviewed)

- Target acceptance: synthetic JST edge clocks including UTC-offset inputs, same-day skip and exact midnight recheck, work A/B independence, `cooldown_hours=23` ignored, timezone-aware clock validation, future/inconsistent state fail-closed, and local-skip page/request count zero. Confirmed-consumption capture failure remains resolved from its corresponding persisted run; unknown consumption remains blocking across restart and date changes.
- Discovery uses visible row-local positive evidence: one exact visible `無料` marker is `free`; a single visible price slot with recognized public S/G image alt+asset is `paid`; a fully joined row with no price/free/access marker is `quota`. Hidden, missing, malformed, conflicting, multiple, or unfamiliar rights indicators remain `unknown`. `pointConsumption`/`badge` are not used.
- Site Policy exposes only `work_ticket`; free remains direct, quota is work-scoped and limited to one candidate per work, and premium/coin/medal/purchase paths are unsupported. Ticket retry time is computed to the next 00:00 JST boundary; `work_ticket_cooldown_hours=23` is ignored. Past retry timestamps are suppressed by shared inventory display logic.
- The optional site-neutral work-history hook blocks markerless, malformed, running, identity-drifted, or otherwise unconfirmed quota attempts across different episodes, new Batch invocations and date changes. Identity binds through Catalog item→work IDs, the source composite external ID, immutable CrawlRun snapshot and canonical viewer target; `Work.work_key` is user-managed and is not interpreted as a site-native ID. After both persisted source consumption and the exact work/resource ledger agree, a versioned immutable confirmation marker is written in the existing CrawlRun `stop_reason`; confirmed consumption followed by capture failure is resolved without another ticket. No schema change was made. Generic history marker text is not yet stripped in GUI presentation; Root will assess at Phase 04 audit.
- Planner removes candidate works with unresolved history. The CLI calls the Executor local gate before Page creation for normal and grant-only, and the Executor rechecks history internally before entry. Local daily and unknown-history skips create no Page/CrawlRun. An active episode grant remains direct during a Work's daily ticket reset. No automatic retry is allowed for ambiguous attempts.
- Anonymous/login live probe used existing CDP `http://127.0.0.1:9222`, with a disposable context and no shared state. Work 3667 classifications matched exactly (25 rows, 1 free, 1 paid, 23 quota). No charge action, episode selection, viewer navigation, Catalog/Watchlist/output write, or ticket use occurred. The other four works were not repeated anonymously.
- Targeted tests PASS: combined `tests/unit/test_comicfuz_discovery.py tests/unit/test_comicfuz_policy.py tests/unit/test_inventory.py` — 77 passed; `tests/integration/test_comicfuz_discovery_browser.py` — 27 passed; `tests/unit/test_batch_executor.py -k comicfuz` — 2 passed; `tests/unit/test_comicfuz_adapter.py` — 8 passed, confirming the existing free adapter contract. After the independent review additions and `work_key` fix, `tests/unit/test_comicfuz_policy.py tests/unit/test_batch_executor.py -k comicfuz` — 21 passed. Existing pytest-asyncio deprecation warnings only.
- Root affected regressions PASS: `test_batch.py`, `test_batch_executor.py`, Hanayume/Younganimal/ComicDAYS policies — 254 passed; CLI grant-only/resource/cooldown/candidate-retry selection — 22 passed. These are root-run and were not repeated here.
- Static checks: `git diff --check` PASS. Scoped Ruff for changed source/tests with `RUF100` suppressed PASS; the only RUF100 in that scope is an unrelated pre-existing noqa in `tests/unit/test_batch_executor.py`. Root compared full Ruff results to `main`: its 13 baseline findings are unrelated and the two findings from this change (import ordering and new unused noqa) have been corrected. Full `ruff check src tests` is therefore not claimed clean.
- Pending independent Phase 02 review: no production Phase 03 entry work has started. Positive consumption response, native consumed timestamp and grant expiry remain Phase 03 design prerequisites. Full repository pytest was not run; the selected integration module baseline history above is incomplete, not a full pass.

### Phase 02 independent review (2026-11-24)

- **PASS; BLOCKING=0.** Independent reviewer validated the policy/Executor contracts, inventory boundary, arbitrary user-managed `Work.work_key`, notes, and Page-generation gate description. Reviewer test selection: 21 policy/Executor tests + 4 inventory tests passed; `git diff --check` passed.
- The review's first blocking findings were resolved before this gate: (1) active episode grant is direct/non-consuming and independent from Work daily reset, including exact expiry and malformed-naive timestamp cases; (2) Work identity binds through Catalog item→Work relation and source/target native identity, never by parsing user-managed `work_key`; (3) current notes describe free/paid/quota behavior and historical direct-only details as superseded; (4) docs distinguish CLI local gate before Page creation from Executor's internal entry recheck.
- Phase 03 production changes may begin under the Lead's contract. Charge click remains prohibited until Gate03 synthetic/review approval.

## Phase 03 — Adapter entry / normal Batch / grant-only (native-contract research)

- Scope: inspect first-party charge handler and public response/state contracts read-only before implementing; determine positive consumption evidence, consumption timestamp and any explicitly observed episode grant expiry. Do not infer a fixed duration.
- No live `チャージで読む` click has occurred. No ticket has been consumed. Live click remains gated on Gate03 synthetic tests and independent review, then only the minimum user-authorized count.
- Implementation acceptance: adapter-local only for `auto` / `direct` / `quota`; only `work_ticket`; same-page one-click latch, pre-click durable observer, exact episode/work identity and zero-price work-charge control, typed positively proved no-action outcomes versus unknown hold, no automatic retry/navigation after timeout or cancellation. Normal quota capture reuses current viewer/END flow. Grant-only confirms entry/consumption and stops before image body read/save, ZIP, Artifact or Completed status.
- Phase 03 test acceptance: synthetic one-click/zero-click, unknown attempt blocked across restart/date/other episode, positive consumption then capture failure remains resolved, exact identity drift, AccessGuard denial, same Page continuation, entry-only no image-body read listener. No shared Catalog schema, existing image-role, capture or END changes.
