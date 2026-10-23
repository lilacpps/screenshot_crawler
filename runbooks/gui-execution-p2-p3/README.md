# Windows GUI: P2 実行操作 / P3 ジョブ管理 — 実装Runbook

> **PLANNED / NOT IMPLEMENTED** — 2026-10-23
>
> 既存P1をベースに **P2 → 品質ゲート → P3 → 最終レビュー** まで実装するための実行契約。P2・P3をまとめて進めてよいが、P2の候補範囲とリソース消費安全性が証明されるまではP3へ進まない。
>
> 範囲外: P4スケジュール、P5 Watchlist編集・Scope Sync apply・同一site key間Source移管・ZIP Rename・再取得管理。実サイトでの有償購入、quota/ticketの実消費検証も行わない。

## 0. 基準と目的

2026-10-23 main (`5382b046bd93ed7848721a966a60229e3f1ef9c8`)でP1は導入済み。着手時にHEADを再検証する。

- `src/screenshot_crawler/gui/main_window.py`: QTreeView、右詳細、チェック済Watchlist key群、P1時点でdisabledのDiscover/Batch/Grant-onlyボタン。
- `src/screenshot_crawler/gui/model.py`: 選択は`InventoryTreeModel.selected_keys()`（stable Watchlist keys）で、focusとは分離。サイト別／作品別でも保持。
- `src/screenshot_crawler/management/inventory.py`、`models.py`、`catalog_reader.py`: read-only Snapshot/summary/Policy状態。**在庫の概要は実行計画ではない**。
- `src/screenshot_crawler/batch/planner.py`: `plan(site, now, quota_resource, output_mode)` が現状の単位。正確な対象keyフィルタはまだない。
- `src/screenshot_crawler/cli.py`: `discover --key/--site/--all --mode full|incremental`、`batch plan/run --site`、`batch run --grant-only RESOURCE|all --limit N`。追加resource pass・deferred resolver・post-grant再Plan・metrics出力あり。
- `src/screenshot_crawler/discovery/service.py` と `batch/executor.py` はCatalog job_lockによる更新排他を持つ。`enabled:false`のDiscoveryは実行せず`stopped_reason=disabled`。
- Catalog v7 / `acquisition_enabled` / Scope fingerprint gate / Site Policy / archive collision preflightは現行のまま正本。
- P1の`CatalogInventoryReader`は完全非変更のためWAL形式を拒否する。P2/P3でもこの設計を勝手に緩めず、**実行用Catalog**と**一覧の読み取り**の扱いを分離してGUIへ明示する。`management.sqlite`は別DB。

**達成目標**:
1. サイト／作品／keyのチェック群を対象に、Discover・Batch Run・Grant-onlyを安全に実行できる。
2. 実行前に「選択された本当の候補／スキップ／未知／Resource消費の可能性」を確認し、確認時と開始時の差異を検出できる。
3. 複数サイトを順次実行し、処理中の進捗、完了結果、失敗、停止と再実行を永続履歴で追える。
4. 既存の`--site`全件CLI、Scope/Quota/Grant/Archive安全装置、P1表示と通常CLIの挙動を維持する。

**読み物・権限順**: `AGENTS.md`、`docs/SPEC.md`、`docs/ARCHITECTURE.md`、`docs/DISCOVERY_AND_BATCH.md`、`docs/ACCESS_CONTROL_AND_PACING.md`、`docs/MAGAPOKE_BATCH_ACCESS.md`、`docs/TEST_STRATEGY.md`、`docs/CODEX_IMPLEMENTATION_GUIDE.md`、`docs/GUI_INVENTORY.md`、`docs/GUI_README.md`、`runbooks/gui-inventory-p1/PROGRESS.md`、`runbooks/work-key-archive-order/PROGRESS.md`、既存code/tests。

本書はrunbookであり実装済みと混同しない。変更した契約が上位authorityと衝突する場合は記録し、同一変更でdocs/noteを更新する。

## 1. 画面・操作の要求

### 1.1 既存P1の延長

既存のサイト別`site→work→key`／作品別`work→site→key`、検索・checkbox・右詳細・取得進捗を維持する。**GUIを書き直さない**。

下部のDiscover / Batch Run / Grant-onlyボタンを有効化し、いずれも最初は**確認ダイアログ**を開く（クリック一発でsiteへアクセスしない）。ダイアログの確定ボタンでジョブをキューへ送る。実行中もInventoryの閲覧は可能。

- Selected keysの集合は「キーID」で固定。検索で隠れたkeyも含むこと、対象サイト数、key数、作品数、対象Workの正確な名前を確認画面に表示。
- 親チェックはすべての子key対象。無効Discover key、未Discover key、未管理Source、Scope stale等はsiteごとに事前検出して理由を表示。自動Watchlist修正は禁止。
- DiscoverにはFull / Incrementalの選択。`enabled:false`は実行対象から除外し明示SKIP; 有効なkeyだけ残る場合のみ実行許可。
- Batch Runには最大取得数（**サイトごと**）、直取／quotaプール／追加resource pass、スキップ理由、衝突とScope gateを表示。quota実消費は起動後のsite状態に依存。
- Grant-onlyにはsiteごとのPolicy提供`grant_only_supported_access_resources()`から対応resource一覧と`all`を提示。対象が異なるサイトならsite別resourceを選ぶ／未対応サイトを除外することを明示。対応不明のResourceは推測せず拒否。
- PreviewはPlanner等の既存serviceを再利用して実行直前にもう一度検証。Scope/選択key/対象Source/Access/Quota/ZIP pathが実質変化した場合は再確認、または明示安全停止。**確認時のplanをそのまま無条件に実行しない**。
- 実行が安全なものだけ開始する。複数サイトで1サイトがblockingの場合、初期仕様はジョブ全体を開始前にblockingとする（silent partial executionを防止）。実行後にsite失敗した場合の次siteへの継続/停止規則はP3で明示。
- Preview値は「planning時点のローカル候補」、進捗値は「実行観測」。ライブで得ていない可用性を成功と表示しない。

### 1.2 ジョブ管理（P3）

P1の主画面へ「ジョブ」タブ/画面を追加。キュー、実行中、最近の結果を表示。ジョブ選択で子siteタスクとkey/Item単位のprogress、stdout/stderr構造化イベント、metricsパス、原因詳細を確認。進捗は**作業単位が確定している場合のみ比率**、deferred/unknownの総数は不定表示。終了後は読取Snapshotを非同期reload。

- Job = 一度の確認操作で登録された`selected_keys`集合と実行設定。
- Task = Job内のサイト単位（サイトは明示した順／安定した順に逐次実行、同時は1）。
- Events = 各対象・Resource pass・状態変更・警告／失敗を構造化記録。ログ表示とイベント履歴の両方を持つ。
- Status: `queued, planning, running, succeeded, partial, failed, cancelled, interrupted`。`no_candidates`と`skipped`は実行成果の区別として残す。終了時の成功は消費/取得の確認に根拠がある場合のみ。
- 再実行は**新しいJob**を作り、Catalog・Watchlist・Scope・Site Policyから再Plan。古いCandidateやチケット/Quota予約をリプレイしない。直近にresource消費したが確認不能な件は**手動確認を促し、自動再実行しない**。
- GUI通常終了時、実行中Jobの停止要求・保存状態を案内。GUIクラッシュ時は「ジョブが終了した」と推定しない。起動時に未完了Jobを検知し、PID/worker identity/lock/heartbeatと照合し、running workerが残っていれば再接続または安全停止。確証がなければ`interrupted / 要確認`とし自動再開禁止。

## 2. バックエンド仕様 — 選択キーによる実行（P2の中心）

### 2.1 共通のSelector

`ExecutionSelection`等のQt非依存DTO:
- `selected_keys: frozenset[str]`（非空）
- `site_grouping: site → ordered keys`（Watchlistから導出）
- `action: discover | batch | grant_only`
- `discover_mode: full | incremental` / `grant_resource`/`limit`/`paths` 等を別DTOで保持。

実行要求では、Watchlistに存在するkeyか、宣言site/work_keyとの一致、duplicate/selection orphanなし、enabled-for-discovery（Discoverのみ）、Catalog同期状態とreadiness（Batch/Grantのみ）を検証。GUI `KeyInventory.identity`のsynthetic unmanaged keyは要求に入れない。**Watchlist.disabledはBatch/Grantの担当外判定ではない**（`acquisition_enabled`とは別）。

サイト順は初期版ではWatchlistの最初の出現順等で決定的にし、UIに表示。サイト内の候補順・Site Policy依存のquota配分は既存Plannerに委ねる。

### 2.2 Discover

既存`DiscoveryService`とCLIの`--key`を再利用。選択集合をsite別に順次実行できる薄いorchestratorを追加。サイト単位の選択で既存`discover --site`を流用して非選択keyを含めないよう、**常に正確な選択key** を渡す。

Full/Incrementalの結果を`observed/new/known/complete/stopped_reason/warnings`付きで記録し、失敗したkeyを個別に特定。`incomplete`をsucceeded扱いしない。Scope Syncは暗黙applyしない。DiscoveryでScope staleになった場合、Batch/Grantを自動キュー投入しない。明示「Syncが必要」を表示。

実Catalogに対するDiscoveryは実行要求の明示確認後だけ。Catalog Job Lockは既存DiscoveryServiceの契約を尊重し、同時ジョブを避ける。多site/多keyで途中失敗が起きた場合の続行規則を確定する（既存multi-key Discoverは個別key失敗を収集して継続可能だが、リスクが高いaccess_stop等は停止優先）。

### 2.3 BatchPlannerと実行時のselected_keysフィルタ

現在`BatchPlanner.plan(site, now, quota_resource, output_mode)`がsite全体を計画する。`selected_keys`を**明示的オプション**として追加し、`None`は従来のsite全件動作、空集合は **候補なし（または明示拒否）**で「無指定」と同義にしない。

- `selected_keys`のキーがWatchlistに存在し、`site`と一致することを事前検証。対象work_keyに属する他site/keyもScope fingerprintを検証する既存安全性を保持。
- `sources`全体（site全Source、quota_consumption history含む）は`policy.available_quota`の計算に残す。**選択Sourceのみで残枠を過大算定しない**。
- `selected_keys`による候補絞り込みをSite Policy選択、`_enforce_work_quota_limits`、`quota_available`割当、`--limit`/site orderingの前に実施。非選択keyがQuotaを使い切った扱いにならない。
- `acquisition_enabled`、unknown Watchlist ownership、Item status、available、Scope-sync gateは既存より緩めない。
- `item`に複数Sourceがある場合、選択キー外のSourceへ自動フォールバックさせない。曖昧/重複所有はfail closed、必要なら診断。
- archive-order命名には**同一work_keyの全site/key**のデータを残す。選択フィルタで番号を詰めたり、Source IDのつけ直しや外部keyの欠落を招かない。
- `BatchExecutor`の候補再検証、resolver、preflight/packaging時のsource ownershipも選択集合と一致させる。後の再Plan／Resource pass／post-grant direct／grant-only allの**全経路**に同じselectorを渡す。
- GUIだけでフィルタリングする、Planner計画後に末尾で`plan.candidates`を削る、サイト全体を実行した後に事後集計する方式は禁止。
- CLIも `batch plan/run --key KEY` 複数指定等、明示的なinterfaceを追加してheadlessで再利用。引数なしの既存`--site`動作を維持。`discover`も複数key指定のCLIは必須ではなく、正確なkeyの逐次処理なら可。
- Site Policyのquota上限・scope / sourceの選択順・追加resource passを変更しない。`paid`/無権利への自動購入・既存アクセス制御の緩和は禁止。

### 2.4 Grant-only

- `--grant-only RESOURCE`と`all`の既存リソース検証、deferred quota live resolver、grant-only skip/retry、after_observed_consumption契約を維持。
- ローカル`Policy`とCatalogの受給状態をPreview。実サイト未接続なら「今使える」と断定しない。
- 実行ごとの`Resource`、対象`work_key/key/source_id`、試行数、消費観測、`SKIP/NG/succeeded/unknown-consumption`を区別。
- Resourceが作品単位なら、Workに複数keyがある場合でもSite Policyの`one work at a time`やwork共通resource stateを厳守。
- 選択したsite/keysの外からresolverがsource IDを選ぶ、grant-only allで追加Resource passのreplan時に対象が拡大する事象は**hard error**。
- GUIの最大件数は通常Batchの「取得スロット」、Grant-onlyの「試行数」なので表記も区別。両者を同じ完了件数として扱わない。

### 2.5 実行前計画・確認

Qt非依存`ExecutionPlanService`を提供。**読取・事前確認だけ**でsiteアクセスなし、Catalog更新なし。`BatchPlanner`のread-only planと`ScopeReconciler`、`SitePolicy`をauthorityにする。

- `preview()`は構造化DTOを返す（site/work/key breakdown、候補・skipped reason・Resource、quota slot、blocker/warning、確認時指紋／revision、時刻・Catalog/Watchlist path、snapshot identity）。
- `confirm`で作る要求は操作種別とkey集合を固定。実行プロセスで開始直前に**同一条件で再Plan**し、消費開始前のcritical changed candidate set、Scope/URL/permission/resource/path差異はabort/再確認。期限の自然経過やサイト固有変動の設計は丁寧に整理し、観測値が変わっただけで安全とは限らない。
- Previewで不明、Scope未同期、異site key、読取DBと実行DBの不一致があれば実行しない。単なるArchive履歴warningとhard collisionを区別し、現行Batchの警告／ブロック規則を保持する。
- live resolver実行後の変化は既存の正当な`replan`として許可し、**選択集合の維持は再検証**。完全一致のCandidateが永遠に変わらないことを期待しない。

## 3. P3の基盤: 実行・Job DB・進捗

- GUI内でCrawlerを直接`asyncio.run`しない。`QProcess`または`subprocess`で **別Python worker process**を起動し、Qt UI threadとSite/Playwrightを分離。`sys.executable -m screenshot_crawler...`と引数配列を使用し、`shell=True`やユーザー入力をshell commandとして組み立てない。
- **一度に1 worker / 1 active Job**。Catalog job_lockが別CLIとの競合を防ぐ（既存ロックを上書きしない）。siteは1つずつ実行し、shared CDP sessionを同時操作しない。キューはGUIから管理する。
- Job状態はCatalogとは**別SQLite**（例: `output/management/management.sqlite`、別ディレクトリ指定可）。ログは`output/management/logs/<job_id>/`。メインCatalogのv7スキーマ変更は原則不要。
- 最小表: `jobs`（id、作成者=GUI、action、selected_keys_json、options_json、状態・時間・リクエスト指紋・worker identity）、`job_tasks`（job_id、site、selected_keys、状態、候補/試行/成功/失敗/スキップ、metrics/log path、時刻）、`job_events`（job/task、sequence、event type、item/source/resource、確認済結果、error/stop reason、時刻）。job DB schema version/migrationと安全なバックアップ方針も実装。
- stdout/stderrをそのまま正規表現で解析してprogressを作らない。共通run contextが出す **append-only JSONL events** または`--events-file`を設計。Writerはworkerプロセス、DBへの状態変換はJobController側等、**権威を1つに**して二重writerの整合性競合を避ける。タスク/イベントIDによるidempotency（重複取込・再起動復旧）を保証。
- event contract例: `job_id, task_id, seq, at, type, phase, site, key, work_key, item_id, source_id, resource, status, reason, resource_consumed, metrics_path, error_type, error_message`。ログ/イベントにはCookie、token、URL query secrets、認証情報、ページ本文を保存しない。
- SitePolicy quota stateと既存Catalog`crawl_runs`、`artifacts`、`output/metrics`が成果のauthorityであり、management DBは**GUI操作と進捗の記録**。矛盾時はCatalog/metricsに従い、未確認を成功としない。
- discover成功数、Batch candidates attempted/finished/captured、grant消費観測とunknownを分ける。進捗率は`known_total`時のみ表示。deferred resolverやquota availability unknown時は不定進捗。
- 日常の再実行は`Retry as new job`（現在のCatalog/Watchlistから再計画、同じ選択keyと設定を入力として再確認）。元Jobをそのまま再開しない。既存ZIPを上書きしない。
- キューはsite別に分割した親Jobと逐次Task。途中でSiteが失敗した場合は残りを`not_started`とし親`partial/failed`を正確に記録する。初期方針として fail-stop（後続Siteを勝手に実行しない）を推奨。
- 起動時の未完了Job: 実PIDの生存に加えworker起動トークン/job_id等の同一性を検証。確実ならイベント再接続、確証がなければ停止/不明表示し**自動再実行しない**。単なる`running` CrawlRunをlive実行の証拠にしない。
- stop: Queueに対する取消し、activeには取消しリクエストを渡して**候補間の安全境界**で協調停止（`--cancel-file`等）。強制killは別の非常手段で、消費不明を生み得ることをUIに表示。キャンセル中も「キャンセル完了」と言わない。ユーザーのGUI closeは活動Jobを確認し、停止要求/そのまま待機を選ばせる。
- 親ジョブでデータ取得・リソース消費確認が失敗した場合、その候補の自動再試行なし。`after_observed_consumption`を尊重し、unknown-consumptionは手動確認対象としてGUIで目立たせる。
- GUI再起動やJSONL切断/partial line、child crash、log write failure、job DB inaccessible、metrics unavailableはテストし、fail closedにする。`no_candidates`を「取得成功」や「リソース消費成功」と表示しない。

## 4. GUI導線

`P1 MainWindow`の下部実行ボタンを有効化し、`ExecutionPreviewDialog`を実装。ジョブを確定すると`JobsPage`へ移動できる。Inventoryの表示・フィルタ状態は保持。

- 実行前ダイアログ: 種別、Full/Incremental、対象site/key、site別resource、上限、計画件数、今はスキップされる理由、Scope/lock blocker、重要なwarning、【実行】確定。
- Job画面: queued/running/finished件数、親Jobとsite task一覧、現在のsite/key/item/resource、結果件数、ログ/metricsへの参照、停止・新Jobとして再試行。
- 必要に応じて`JobsPage`をMainWindowのstacked page/tabとし、初期画面のレイアウトを大きく変更しない。
- ブラウザ接続（標準`.chrome-crawler`/CDP）、環境ファイル、Catalog、Watchlist、runtime、library/output/metricsパスを明示してworkerに渡す。sample/catalog copyと本番を混在させない。
- プロセスの結果だけをみて全candidate成功としない。job/task resultは候補ごとの観測・メトリクスを集約する。

## 5. 実装順序と品質ゲート

- **P2 / Execution**: [02-execution/README.md](02-execution/README.md) — selector、Planner/CLI、Batch/Grant再Plan safety、Discover、preflight/GUI操作、isolated no-site verification。
- **P3 / Jobs**: [03-job-management/README.md](03-job-management/README.md) — 単一worker、management DB、event/recovery、stop/retry、JobsPage、Windows/Qt QA。
- [PROGRESS.md](PROGRESS.md)にフェーズごとの実装結果、テスト、Reviewer判断、未解決問題を記録。

各フェーズで:
- Leadがspec/acceptanceと既存制約を再確認。Implementerは主writer、Reviewerは独立・read-onlyで誤取得・quota二重消費・grant誤表示・cancel不整合を重点レビュー。必要時Testerがisolated Windows/Qt E2E。
- Targeted tests → affected contracts tests → integration (fake CDP/workerのみ) → shared refactor/影響大ならfull suite → Ruff。`docs/TEST_STRATEGY.md`に従う。
- 関連`docs/DISCOVERY_AND_BATCH.md`、`docs/GUI_INVENTORY.md`、`docs/GUI_README.md`、`note/00_core.md`、P1 GUI note等を実装と同一変更で同期。
- P2 blockerが残ればP3へ進まない。P3終了後は本番Catalog/Watchlist/Booksの非意図変更がないことと、互換CLIの回帰を確認。

**セキュリティと実動作**:
- 自動テストはtemp Catalog / Watchlist / library / management DB / metricsとsynthetic workerで行い、現実のチケット消費・購入・課金操作なし。
- サンプルの`tools/gui_sample.py`や運用データを本番用と誤って実行することを防止（明示的なパス確認/guard）。
- 実サイトを利用したGrant-only / Live資源消費はユーザーが別途明示承認しない限り行わない。Readonly GUIの見た目確認は可。
- プロダクションZIP rename、Source移管、Watchlist編集、Scope applyは今回実装しない。

## 6. 最終受け入れ条件

1. 正確な`selected_keys`でDiscover（Full/Incremental）、Batch、Grant-onlyを実行でき、選択外のSource/Workが現れない。フィルタで隠れた選択もGUIで明示される。
2. Quota残枠はsite全Sourceを考慮しつつ、**選択内候補だけ**に割り当てられる。named resource/all pass/deferred/post-grant replanでも同じ。
3. Scope未同期/欠落key、Site Policy unsupported、archive hard collision、stale reviewがサイト接続/消費前に拒否される。
4. Discover disabled keyはskipを明示し、Full incompleteを成功扱いしない。Scope同期は暗黙applyしない。
5. Jobは単一実行、永続履歴・部分失敗・再起動/中断復旧、協調停止、無条件自動再試行なし。
6. 既存`batch --site`/`discover --site/all`/P1 inventory/Qtの機能・Quota/Resource安全契約への回帰なし。
7. コマンド例、確認ダイアログ・Job一覧のスクリーンショット、隔離データでのE2E、Windowsでの操作確認（不可能なら未検証明記）を提示。
8. P3終了時に画面レビュー用成果を提出。**P4/P5の実装には進まない**。

## 7. 今回は扱わない「少数だけ別サイトから取得」ケース

`Magapoke → Comic DAYS の2話 → Magapoke`のようなWatchlist 3-key管理、`archive_order`、Scope Syncは現行で表現可能。既存同一siteの`discovery_key`を別keyへ再所属させる操作やSource削除は**このrunbookでは実装しない**。後のWatchlist編集フェーズで、既存Source ID・CrawlRun・Artifactを保持しつつ、境界確認・dry-run・同期・collision検査付きの限定的key移管を検討する。勝手にSource削除して履歴を捨てる実装は禁止。
