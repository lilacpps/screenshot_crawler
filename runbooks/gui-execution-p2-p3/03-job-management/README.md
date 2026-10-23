# P3 — ジョブ履歴・単一worker・安全な停止／再実行

> **PLANNED / NOT IMPLEMENTED**
>
> Prerequisite: [P2 reviewer-approved gate](../02-execution/README.md)、[master runbook](../README.md) の契約を満たした実装。P2ブロッカー解消なしにP3開始不可。
>
> **Exit:** ジョブ監視GUIをWindowsで試せる状態まで実装。P4（Schedule）/P5（Watchlist/Source移管/Rename）は実装しない。

## 1. Objective

P2で「選択されたsite/key群を安全に実行する」基盤を、日常運用できる**単一workerジョブキュー**へ接続する。Batch/Discover/Grant-onlyそれぞれの実行前確認、進捗、成功/失敗/取消、過去履歴、再計画して再実行する操作を、P1 MainWindowを生かしつつ提供する。

P3はスケジューラ・常駐デーモンではない。GUIプロセスがJobControllerとなり、実作業は別worker subprocessで実施。複数アプリ/別CLIの同時実行は既存のCatalog job_lockで衝突を安全に止める。

## 2. P3.0 — Job/Task/Event 契約

### 2.1 データモデル

Catalogとは別の独立DB（初期default例: `output/management/management.sqlite`、オプションで変えられる）を利用。Watchlist/Catalog/Books配下へのJob metadata書込み禁止。管理DBのschema versionとmigrationを明示し、存在する破損DBを自動上書きしない。`management.sqlite`の既存ファイルに違うschemaがあるなら安全停止。

最小table:

- `jobs`: UUID job_id, action, original selected_keys_json（stable Watchlist key）, settings/paths redacted reference, requested_at, confirmed_at, planned fingerprint, state, started_at, ended_at, cancel_requested, worker identity/token, summary JSON, original_job_id(nullable)。
- `job_tasks`: task_id, job_id, site, sorted selected_keys_json, resource/mode/limit, state (including not_started), planned_attempts, observed_attempts, success/failed/skipped/unknown counts, metrics_path, stdout/stderr log path, started_at, ended_at。
- `job_events`: event_id/sequence + task_id/job_id, observed_at, event_type, phase, key/work/item/source ID (nullable), resource, result, resource_consumed (tri-state), reason/error_type, safe diagnostic payload。
- Indexes/uniques: job_id+site/order/attempt、job/task+event_seq。Commitとイベント書込みのidempotencyを決めて再生でも二重カウントしない。

状態:
- Job/Task: `queued, planning, running, succeeded, partial, failed, cancelled, interrupted`、Taskには`not_started`（未試行）。
- Event: `job_queued, task_planning, plan_accepted, task_started, candidate_started, candidate_finished, grant_attempted, grant_confirmed, grant_unknown, task_finished, task_failed, cancel_requested, cancellation_checkpoint, process_exited`など必要最小限。
- `no_candidates`は`task_finished`の理由/集計。サイト操作実行ゼロであれば`0件・実行なし`と表示し、`消費成功`と混同しない。
- 観測由来フィールドと推定値を分離。`resource_consumed`は`true/false/null(unknown)`。負債やレンタルの手動確認が必要なケースで`null`を`false`に丸めない。

### 2.2 Paths / lifetime

- 各Jobを独立したディレクトリへ`logs/<job_id>/events.jsonl`、`stdout.log`、`stderr.log`に記録。既存`output/metrics`のファイルはそのpathを記録してリンク。ZIP・Crawler出力は既存構造とCLI互換を維持。
- 外部から渡す`Catalog/Watchlist/runtime/env-file/library/output`パスを、Preview/Job保存/worker起動で不変の絶対パスとして明示。パス組合せの不整合を事前に防ぐ。`sys.executable`利用、`shell=True`不可。
- Token/secret/Cookie/.env本文をJob DB/event/logに記録しない。stdout/stderrにも認証情報が出ないことを確認する。
- GUIは管理DB read/write可、Crawler Catalogの更新は**ユーザーが起動を確定したジョブのworkerだけ**。P1の`CatalogInventoryReader`のWAL拒否・純粋閲覧の境界は守る。

## 3. P3.1 — Subprocess Job Worker・構造化event

### Worker

- GUI`QProcess`もしくは監視用Python JobControllerが`python -m screenshot_crawler.management.job_worker ...`を引数配列で起動。`JobExecutionRequest`を元にし、siteごとに順次処理。PySide6をimportせず、直接CLI/サービスも同じworker contractを使えるようにする。
- 原則1つのactive workerのみ。Queue順はJob登録順、内部site taskは確認画面の安定順。別CLIがCatalog lockを持っていたら安全にwaiting/failed/blocked、ロックを勝手にbreak/削除しない。
- `BrowserSession`は既存CLIの標準`.chrome-crawler`/CDP lifecycleを尊重。プロセス終了時にリモートChromeを終了しない。`--keep-open`等対話的stdin待機はJobWorkerで使わない。
- `P2`で追加したselectorをすべての`planner.plan`/resource pass/Grant resolverに保持。開始直前に計画を再検証し、critical drift時はsiteへ接続する前にstop + new preview required。
- 実行詳細では`candidate_started/completed/skipped/failed`を structured event として出す。`BatchMetricsWriter`/`GrantOnlyReport`は既存authorityとし、必要最小限のevent sinkを足す。CLI stdoutを正規表現で機械処理しない。
- Event JSONLはworker一人がappend、JobControllerがtail/readしてDBにidempotent import（または1つのwriterだけがDBも扱う方式を明示）。Readerは不完全な末尾行を正常eventとして扱わず次回読み込みへ繰り越す。
- 既存`crawl_runs/artifacts/quota_resource_states`との整合を崩さない。Jobのsuccessはexit codeだけでなく観測済event/metricsと照合。「途中消費確認後に保存失敗」等を成功で塗りつぶさない。

### Fail-stop / queue control

- 起動前のプレビューで選択サイトのいずれかがhard-blockedなら**親Job全体を開始しない**。
- 実行開始後site taskが失敗したら原則**残りサイトを開始しない**。`not_started`、親`partial`（一部成功あり）/`failed`（成果なし/重大エラー）に落とす。全件`no_candidates`は零件の正常終了だが「取得成功件数0」と表示。
- 古いJobが`queued`として残っていたらGUI再起動で勝手に自動実行しない。`resume queue`を明示操作にする。
- Resource消費可能性のあるpassは、Plan→Attempt開始→確認結果→更新の観測を記録。途中不明な消費では自動retry禁止。

## 4. P3.2 — 安全な停止 / Crash recovery

### Cooperative cancellation

- GUIの「停止要求」は`cancel_requested`を永続化してworkerへ通知（Job dirのatomic sentinel等）。workerはsite/task/候補間、追加Resource pass前、deferred resolver前に確認。観測中のquota debit / viewer captureを無理に中断しない。**停止要求≠停止完了**。
- 取消し済Jobは`cancelled`/`partial`（一部実行済）へ、次の候補を開始せずクリーンアップ後に確定。実行の残quota/ZIP/crawl runsの後始末は既存executorに委ねる。
- 「強制終了」は別操作。Windows`TerminateProcess`等はリソース消費状態不明を生み得る。確認ダイアログと警告を必須とし、一般の停止操作からは呼ばない。強制kill後は`interrupted`/`消費確認要`、自動再試行なし。

### Crash/restart

- DBの`running/planning`レコードだけでworkerの存在や成功を判断しない。worker PID, start identity/token, job_id, heartbeat, process exit status, job_lock等を確認する。
- worker同一性と生存が確実に示せる場合のみ再接続、そうでなければ`interrupted`（確認待ち）とする。PID再利用、別プロセスに誤接続しない。
- GUIが終了するときactive Jobを見つけたら「停止要求して終了」または「終了を中止」を提示し、暗黙の残置/killをしない。アプリが異常終了したときにworkerが生き残る可能性を記録し、再起動で二重起動禁止。
- Job DB書込み失敗とevent file書込み失敗のどちらかが生じた場合はsafe stop。部分イベントは最小限の復旧ログを残し、観測なしを成功へ復元しない。
- Queueから未開始JobをcancelしてもCatalogに触れない。

## 5. P3.3 — GUI JobsPage / 操作

既存P1メイン画面に「作品管理 / ジョブ」切替（`QStackedWidget`等）を追加し、`ExecutionPreviewDialog`から登録したJobへジャンプできる。

- ヘッダー: active 1、queued N、最近失敗N、Catalog path/worker healthの表示。
- Job一覧: 開始・終了時刻、action、site数、key数、実行モード/resource、状態、確定成功/失敗/skip/unknown件数。
- Job詳細: site taskリストとkey/source/item単位のイベント、ログ・既存`metrics.jsonl`、最近エラー全文（安全にredact）、SitePolicy block/warning。
- 停止ボタンは`running/planning`の時のみ、queuedには「取消」。終了済みには「現在の状態で再計画して再実行」。再実行ボタン押下時にもP2と同じPreview必須。
- defer/live resolver中やall resource passesでは当初候補総数が確定しない場合がある。progress barを`indeterminate`にし、実観測数を表示。根拠のない進捗率を表示しない。
- Job終了をUIが検知したら`InventoryService.load`を非同期再実行し、P1の検索・checked_keys・focused itemを可能な限り保持。失敗時には「古い表示」と明示。
- GUI 1400x850で表が圧迫される場合、Job詳細は画面遷移＋下/右paneで検証する。複雑な可動パネル/ドッキングUIを初期から導入しない。

## 6. P3.4 — テスト / 確認

### Automated (mock/isolated only)

1. management DB: 空DB初期化、schema validation、ロック・2重import、イベント順序/idempotency、途中commit failure、破損DB拒否。
2. Job selection: Site A/B 3keys、1worker、site順、queued次Task、複数Clickの二重起動防止、checked keyとサイト投影を維持。
3. Preview→Run: 計画変化でbrowser接続前停止、Quota site全体計算・selector維持、Grant all/after-observed-consumption扱い。
4. fake worker JSONL: 候補success, skipped, failed, no_candidates, unknown consumption、partial line、out-of-order/duplicate、stderrだけ、非ゼロexit、SIGINT等のcleanup。
5. Cancellation: queued cancel、実行中cancel signal、candidate直後の停止、quota debit中には中断せず次候補を開始しない、timeout時は別の非常操作。
6. Recovery: Child生存・worker token一致、不一致、PID reuse、強制kill/GUI異常終了、management DB不調、未着手queuedの自動開始なし。
7. Qt offscreen: JobsPage表示、Job選択/詳細/ログ、停止要求と終了状態、再実行で新Preview、P1 Inventoryのcheckbox/検索/focus保持。
8. 既存CLI/P2 tests: Batch/Discovery/executor/grant/deferred/Scope/Archive、Qt未インストールでも通常CLI動作。
9. Non-destructive: temp Catalog/Watchlist/Books以外への書込みなし、実Catalogの試験運転なし、secretがmetadataに出ない。

### Local integration

- サイトに接続しないfake BatchExecutor/DiscoverAdapterとSQLite tempで、GUI dialog→worker spawn→events→management DB→JobsPage→Inventory refreshを通す。
- Windows上でのQProcess起動、停止要求、PID/recovery、GUI closeとログ参照を検証。無ければQt offscreenの検証と「Windows未確認」を別報告。
- Runtime config/Chrome CDP接続を疑似注入し、実アカウントでのGrant-only消費をしない。既存`.env`からcredentialをログへ吐かない。
- Large Job event数でGUIが固まらないようlazy table/上限ページング、短い測定をPROGRESSへ記録。

### Reviewer focus

- Workerへ渡すselected_keysがreplan/all passesを通して不変か。
- Item/status/Quota/Archive/SitePolicyの既存authorityを変更・バイパスしていないか。
- Cancel途中や観測不明grantを「失敗・消費なし」と誤記録しないか。
- Re-runで古いCandidateを無条件に繰り返さないか。
- Logsのtoken/env/path漏洩やshell injectionの余地がないか。
- GUI/worker異常終了後に同時2個のCrawlerを起動しないか。
- 運用Catalog / Watchlist / Books に偶発的変更を加えていないか。

## 7. Phase exit / handoff

- P2の安全ゲートが過去にPASSである。
- 管理DB + event実装が恒久的に検証され、P1 GUIが問題なく動く。
- GUIからJob開始→進捗→終了→履歴→新JobとしてRetryの一連の操作をisolated fixtureでE2E合格。
- Cancel/force killの区別、Crash recoveryの動作・限界を文書化。
- `docs/GUI_README.md`、`docs/GUI_INVENTORY.md`、`docs/DISCOVERY_AND_BATCH.md`、`note/00_core.md`や他の関連notesを更新。
- `PROGRESS.md`に最終コミット・pass/fail/skip・Ruff/独立review・Windowsスクリーンショット・非Live理由・未解決を記録。
- **P3完了後はユーザーにGUIの実操作レビューを依頼して停止。P4/P5の自動実装禁止。**
