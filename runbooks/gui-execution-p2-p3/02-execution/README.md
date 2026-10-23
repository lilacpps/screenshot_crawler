# P2 — 選択キー単位の安全なDiscover / Batch / Grant-only実行

> **PLANNED / NOT IMPLEMENTED** — P2完了時に独立Reviewerの安全ゲートを通過してからP3へ進む。
>
> Prerequisite: [P2/P3 master runbook](../README.md)、現行P1 GUIの選択集合、既存Batch/Scope/Policy契約。

## 1. Starting evidence

- P1の`InventoryTreeModel.selected_keys()` はkey IDの集合。選択の詳細フォーカス、表示フィルタ、disabled/watchlistと独立。
- `cli.py`のBatch Planner / Grant-only all / deferred / post-grant replanには複数の`planner.plan(...)`呼出点がある。漏れを許さない。
- `batch/planner.py` はquota slotを`available_quota(site_all_sources)`から算定後、candidate poolを作り、その後`_enforce_work_quota_limits`とsite quota allocationを行う。
- `discovery/service.py` の`discover`は`catalog.job_lock()`とenabled:false skipが既に実装済み。CLIは`--key`を受け取る。
- `batch/executor.py`に`_require_candidate_scope`/候補再検証・grant-only consumption logic・hard ZIP collision guardがある。
- Scope Reconcilerと`archive_order`は既存の正本であり、GUI用selectionで番号を振り直さない。

## 2. P2.0 — 実行インターフェースの現状調査と設計確定

- `_run_batch_run_locked`、`_run_batch_plan`、`_execute_batch_candidates`、`_execute_deferred_grants`、`_resolve_access_resource_candidates`、`_apply_access_resolution`、`BatchExecutor`の現在の候補生成/消費境界を調べ、全てのreplan/resource passを列挙する。
- 主要Site Policy（特にManga ONEサイト共通Quota、Magapoke premium/work ticket、Zeblack作品単位ticket、Hanayume/Younganimal work ticket、Comic DAYS）で、selected_keysが何を除外すべきか例示する。
- `--limit`の意味（normal crawl slots、grant-only attempts）と`grant-only all`のwork/site groupingを保存する。
- `project` API: `ExecutionSelection`（immutable selected key set）、`ExecutionPlanService.preview(...)`、`JobExecutionRequest`をQtから独立定義。GUIでの確認時の指紋/operation optionを明示。
- 同一Workに同site複数key・別site複数keyが混在するfixtureを準備。`archive_order`の通し番号がselectionで変わらないことをfixtureで検証。
- `None`=legacy whole site と`frozenset()`=空選択を区別する。明示空選択でsite全体が実行されることを絶対に許さない。

**Exit**: コールサイト表、API、candidate/Quota/Source境界、site-specific risk matrixが`PROGRESS.md`に記録される。

## 3. P2.1 — BatchPlanner / CLIへのselected_keys追加

- Planner公開interface例: `plan(*, site, selected_keys: Collection[str]|None=None, now=None, quota_resource=None, output_mode="capture")`。
- 選択keyに重複・未知・site不一致・無効なidentityがあれば事前に明示エラー。`enabled:false`キーは`Batch/Grant`からは自動除外しない（Source.acquisition_enabledとは別）。
- 対象候補のSourceを`discovery_key in selected_keys`で選択、Catalog側のWork/site/item/source identityとWatchlist bindingを照合する。選択外Sourceへのfallbackは拒否。
- Site Policyに渡すquota accountingは**選択前のsite全Source**に基づく。quota候補の採択・並び順に入るのは**選択対象のSourceだけ**。
- Sync gateは対象Workについて**work全体/関連site横断**で検証する。選択されなかったその他Workに独立に問題があってもsite全体を不必要に停止しないが、名寄せ/Scope/Archiveの関連Work前提を弱めない。
- `Plan`の`skipped`に選択外の大量Sourceを含めるかは既存CLI互換性と表示負荷で決定。選択外はquota消費/候補に絶対含めないことが本質。
- Archiveの`build_work_archive_position_plan`はWork全体のsource集合を使用し、選択内件数で番号を振り直さない。
- CLI `batch plan --site SITE --key KEY [--key KEY ...]`、`batch run --site SITE --key KEY ...` を作る。option absentの既存動作維持。明示パス`--catalog/--watchlist/--library-dir/--crawler-config`等も維持。
- Service/CLI内部の呼出しを複数系統に複製せず、共通Plannerに集約する。GUIのボタンから`batch --site`をshellで実行し後段フィルタするのは禁止。

**Acceptance tests**:
1. 2 work/同site/共通quota=1: 未選択Workが先に並んでも選択Workのquota候補が優先される。**Quota残枠自体はsite全体の使用履歴を尊重**。
2. `selected_keys=None`の結果が既存site全体Planと一致。`selected_keys=[]`はsite全体を実行しない。
3. Work一部keyのみ・disabled key・別siteの無効key・不正site/unknown keyは正確。
4. Scope未同期/owner不一致、paid、out-of-scope、multiple Source、Archive ordinalが選択で変化しない。
5. `--limit`で`selected_keys`から確定したpoolに上限適用。正常プレビューと実行計画の同一選択条件を保障。

## 4. P2.2 — Grant-only とすべての再Planにselectorを伝播

- `grant_only=RESOURCE/all`、Policy `ordered_access_resource_passes`、deferred resolver、local skip、`execute_grant_only_candidate`、resource-specific add-on passes、post-grant direct、`BatchExecutor`の再検証を列挙・テスト。
- 各`planner.plan`呼出しへselectorを明示伝播する。`grant_only all`で前Resource消費後の再Plan時に非選択keyが混入しないこと。
- Live resolverが返す`selected_source_ids`が、`candidate set∩selected key ownership`に属することを最終段で検証。異なるWork・Sourceに意図せずgrantしてはいけない。
- 共通Quotaと作品単位Quotaのresource ledgerを選択key数で分割・再初期化しない。
- 後続passへの`--limit`の影響、local skipped counts、`resource_consumed=False/True/Unknown`の区別を維持。
- Grant-only不対応site/resourceはPolicy error。GUIが`supported_access_resources`ではなく`grant_only_supported_access_resources`を使うことを確認。

**Acceptance tests**:
1. work_ticket / premium_ticket が混在するMagapokeで、選択1Workにしか消費対象が出ない。
2. deferred resolverのmockが非選択Source IDを返したら消費前に失敗。
3. all resourcesの連続replanでselectorが保存。
4. after-observed-consumptionの例外時に追加消費/自動再試行をしない。
5. shared site quotaを選択Work数でリセットしない。
6. Existing ``test_batch_acquisition_scope.py`、`test_deferred_grants.py`、`test_batch_executor.py` 等の関連回帰を維持。

## 5. P2.3 — Discover / ExecutionPlanService

- Discoverは選択`key`ごとに既存`discover --key --mode`を利用する薄いorchestratorを構築。サイト単位複数keyの実行はWork/Resourceと競合しない順序で実施。選択外を含む`discover --site/--all`を代用しない。
- `enabled:false`を事前検証し、skip理由をPreview/結果双方で出す。未Discoverは正常にDiscover可、Scope未同期なら後のBatchを自動開始しない。
- `DiscoveryResult.complete=False`、`stopped_reason=incomplete`をfailed/incompleteと表示。1件のsite-local失敗で他siteを続行するかは`fail_stop`原則とし、結果に`not_started`を残す。
- Qt非依存`ExecutionPlanService`はActionによって計画結果をDTO化:
  - Action、selection、site groups、mode/resource、limit、known candidates、direct/quota pool、skips、blockers/warnings、plan fingerprint、解決したパス。
  - Refresh/Confirm時の差異を検証。`Watchlist`/`Catalog`が変化した場合のCritical diffは再確認。Previewで未確認のsite条件は推測せず未知。
  - 事前確認は**read-only、外部サイト/CDP接続なし**。DB不在・破損・Sync不一致・unsupported resource・archive collisionは明示エラー。
- 実行プロセスでは外部アクセスより前に再Plan/再validate。ライブ状態の変化は既存resource resolverへ委譲する。
- 安全に隔離Catalogを使うfixture、CLI unit、Policy unit、GUI Preview snapshot unitを作成。

**Acceptance tests**: 選択サイト/key/Work数と件数表示が実際のPlanに一致。Scope staleやbroken Watchlistの場合、確認ボタンを押しても`BrowserSession.connect`に到達しない。

## 6. P2.4 — GUIへの確認導線とP2ゲート

- 既存P1の`MainWindow`から checked_keys とpathを取り出し`ExecutionPreviewDialog`へ。既存Focus/Selection/Filter/Search UIの動きを破壊しない。
- ダイアログ: SiteごとのAction/limit/resource、対象key一覧（非表示選択を含む）、blocked/skip、candidate数、ローカルQuota枠と「実際に消費される可能性」注意。Grant-onlyは明示的「権利を消費する可能性があります」を必須。
- P2で起動確認まで検証するため、処理本体をGUIスレッドで実行せずworker入口を用意。ただしP3完成前の仮Queue/Job DBを過剰実装しない。P3用の`JobExecutionRequest`のstable interfaceを先に固定してよい。
- P2 Test Gateは **GUIボタンから所定の選択キー以外のsite処理が開始されないこと**と、Quota/Grant選択不変が最優先。
- CLI regression、local isolated executor/Playwright fake、Qt offscreen confirmation、full/targeted affected tests、Ruff、独立reviewを実施。実チケット消費/課金を伴うLive検証は禁止。

## 7. Critical review / exit gate

Reviewerは次の点をコード/テストで確認:
- Site全件計画の最後で単純filterしていないか。
- `planner.plan`のどのコールサイトもselector伝播漏れがないか。
- 同一siteに複数Workがある場合のquota allocation・work_resource stateの保持。
- 途中でresource consumo unknownとなった後のreplan/再試行を黙認していないか。
- Site跨ぎの同一WorkもArchive採番・Scope gateを正しく維持。
- P1 GUIのcheck/nonfocus/detail/disabled selectionが壊れていないか。
- 確認前にブラウザへアクセス・quota消費・本番Catalogへの予期せぬ変更が起きないか。

**Exit**: P2のテストとReviewer BLOCKING=0、最新コミット、CLI/GUI操作イメージ、未実行Live理由を`PROGRESS.md`に記録。満たしたらP3へ進む。
