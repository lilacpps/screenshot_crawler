# Windows GUI — 常設実行モニター・CUI同等ログ・共通サマリ Runbook

> **PLANNED / DOCUMENTATION ONLY — 2026-10-25**
>
> 本Runbookは既存P1/P2/P3 GUIの機能追加を段階実装する契約である。実装はまだ開始していない。着手時はmain/HEAD、`AGENTS.md`、`docs/SPEC.md`、`docs/GUI_README.md`、`runbooks/gui-execution-p2-p3/PROGRESS.md` と現行コードを再確認する。
>
> **最優先の制約**: 実行モニター「より上」の既存GUI構成を変えない。サイト別／作品別ツリー、検索・絞り込み、既存横方向splitterと詳細ペイン、checkbox、選択操作、Discoverモード／limit／site resource／Discover・Batch Run・Grant-onlyボタン、実行前確認の順序と挙動を維持する。モニターを追加するためのwidgetコンテナの組み替えは可だが、既存部品の配置順・設定・操作意味を変えない。

## 0. 目的と現状証拠

ユーザーがGUI実行中に別ウィンドウ「ジョブ」を開くことなく進捗を見られ、CUIで得られる相当の詳細情報を漏らさず、過去にスクロールしても勝手に戻らず、終了時にAction別の意味あるサマリを確認できるようにする。

2026-10-25確認時の主要実装:
- `gui/main_window.py` は path行 → toolbar → 既存横splitter（tree/detail） → action行 → error label。Jobは500ms `_poll_jobs()`、`_start_execution()` からqueue/start。
- `gui/jobs_page.py` は別ウィンドウで `refresh()` が `QTextEdit.setPlainText()` を繰り返す。Eventsは `JobStore.list_events()` の先頭最大500件のうち末尾30件のみ。原文stdout/stderrは開かない。
- `management/job_controller.py` は独立worker stdout/stderrを別スレッドでsanitizeして `output/management/logs/<job_id>/stdout.log` と `stderr.log` に逐次flush。現在は子Python起動でbufferingの恐れ。
- `management/jobs.py` は`events.jsonl`→management DBのイベント取込み、Job/Task状態、集計あり。Task単位のstdout/stderr pathは共通jobファイルを指す（サイト別ファイルではない）。
- `execution_worker.py` のGUI Discoverは `cli._run_discover()` を通らず `_discover_target()` を直接実行。`cli.py` の `_print_discovery_result()` 相当の観測数/新規数/既知数/完了判定がGUI経路では欠け得る。
- `batch/metrics.py` の `batch_summary` は開始・完了・失敗・計画スキップ・時間・stop_reason等を出力。`grant_result` は作品×resourceごとのOK/NG/未実行、理由、`resource_consumed`を含む。`batch/grants.py` の `GrantOnlyReport` がCUIの使いやすい作品別結果を出力する。
- 現在のJobの`summary_json`はworker監督/結果判定中心。**候補件数の唯一の正本とみなして上書き・拡張しない**。

### 要求 / 受け入れ条件（Workstream共通）

1. 上部の表示順・既存操作・横splitterの比率と意味を維持。下部に実行モニター（折り畳み可、上下高さ手動調整可）を追加し、通常画面で実行状況を常時把握できる。
2. Discover / Batch Run / Grant-onlyの3Actionで、既存CUIが表現する処理情報に相当する全情報がGUIから追える。raw textは保存済`stdout.log`/`stderr.log`を表示し、欠落するDiscover結果は実行経路で補う。
3. リアルタイムの追加描画で上方スクロール位置が戻らない。最下部にいる場合だけ自動追従。ジョブ変更時のみ明示的に表示を切り替える。
4. 実行中は現在site・key・item（判明している場合）・実行試行数・観測済結果・状態・経過時間を表示。総数未確定のlive resolver/deferred passを根拠なく百分率表示しない。
5. 終了後はAction別サマリを表示。正常終了0件、計画スキップ、実行スキップ、部分成功、停止要求、失敗、interrupted、チケット消費確認・未確認を混同しない。終了後もログ表示を保持、履歴から再表示可。
6. Qt UI threadをブロックせず、大量ログは表示上のメモリを制限。ファイル自体は省略しない。原文の全文確認（外部アプリで開く、または適切なオンデマンド読み込み）ができる。
7. 既存P2/P3の一worker/lock/選択key/preview fingerprint/quota/取消/強制終了/再計画/秘密情報redaction契約は**一切緩めない**。

## 1. UXとレイアウト契約

- 主画面上部: path行とtoolbarを変更せず保持。既存横splitter（tree:detail = 7:3）と、その**下**のaction行、error labelを「既存領域」として保持。
- 既存領域の**下**に `ExecutionMonitor` を追加。既存領域とmonitorを縦`QSplitter`に収め、上側が縮む以外の配置順を維持。既存QMainWindow statusBarも変更しない。幅980px・高さ600pxで操作が欠けないか検証する。
- モニター見出し: action / job state / site（実行siteまたは直近） /「進行中」「停止要求中」など。既定は小さな進捗帯＋ログ欄（GUIサイズに応じ初期高さ約220-250px）。未実行時は薄い待機表示。手動で畳めるが実行中は見出しを残す。高さ変更は上部の表示構造を崩さない。
- 進捗: current site/key/item、観測済attempt・success・failed・skipped・unknown、elapsed。source/itemが不明なら空欄/不明にし推定しない。percentは総対象数が確定し観測対象と一致する場合のみ。progress不確定時はindeterminateと観測数。
- 詳細: `詳細ログ`（`stdout`/ `stderr` の切替と全文ファイルを開く）、`サマリ`、`問題のみ`（既知のwarning/error/消費不明を構造化イベントから列挙）。stderrをstdoutの末尾に機械的に連結して時系列原文だと偽らない。単一時系列表示が必要になれば後続課題。
- 自動表示: 新しいJobをユーザーが実行確定した際、monitorを展開してそのjobに切替。session queueの次Jobが本当に開始された時点で追従（`queued`を`running`と偽装しない）。手動で履歴閲覧中の明示選択は勝手に切替えない。終了Jobは次Job開始まで残す。再起動時の履歴は従来「ジョブ」から選択可。
- 既存「ジョブ」はキュー・履歴・停止要求・強制停止・再計画の管理画面として残す。モニターに危険な強制終了機能を重複実装しない。

## 2. データ境界と単純な実装方式

### 2.1 Raw Console（raw textが正本）

- `JobController`のstdout/stderr保存を再利用し、workerに対して`-u`または`PYTHONUNBUFFERED=1`を適用して改行単位の遅延を小さくする（親Python/他CLIへの強制変更は禁止）。既存`sanitize_text()`の適用とsink failure fail-closedを維持。
- Qt非依存の`LogTailReader`相当を新設。参照元は`JobStore.job_dir(job_id)`配下の**固定名** `stdout.log`/`stderr.log`（信頼できないevent payloadの任意pathを開かない）。streamごとのoffsetとincremental UTF-8 decoder（複数byte境界）を保持し、追記分を読み込む。ファイル不存在/遅延作成/縮小で安全に再初期化。
- pollは既存500msに同調できるが、1 tickのread bytes・表示追加量に上限を設定。閉じた/非表示paneと同じJobの差分ゼロなら再描画しない。初回過去ログ表示は末尾N bytesだけ読み、冒頭省略を明示、全文はファイルから閲覧。ディスク上のファイルは切り詰めない。
- `QPlainTextEdit`をread-onlyで利用。追記専用、数千〜1万行程度を表示上限とする。scrollbarがほぼbottomのときだけ追従、それ以外は現在の閲覧位置を固定する。大きなtrimの際はviewport上端anchorを維持できることをテスト。ジョブ切替時にoffset/viewを再初期化。部分改行、CRLF、巨大な単一行も安全に扱う。
- stdout/stderrは別パイプなので、両者間の厳密な発生順序を復元できない。UIもその限界を明示し、それぞれ全文を見られることを第一とする。安易に`subprocess.STDOUT`へ変更して既存stderr contractを破壊しない。

### 2.2 Structured progress / results（意味の正本）

- `job_tasks`と`job_events`のobserved factsを利用。現在の`list_events(limit=500)`は「**先頭**500」であり最近500ではない。UIへはSQLで`ORDER BY sequence DESC LIMIT ?`（表示順は昇順へ戻す）またはkeyset/cursor増分で読み、イベント全件の都度再構築を避ける。DB移行なしで新しいSELECT methodを追加可。
- Progress aggregationはQt-freeのPresenter/Reducerに実装。Job ID/actionでscopeを固定し、結果をsite/Task/Work（実績がある場合）に集約。Job terminal stateはController/DB正本であり、Reducerが成功へ昇格させない。
- Batchの完成済数などは`batch_summary`のMetricsを主根拠としてsiteごとに読み、`candidate_started/finished`は実行中の暫定progressに利用。計画スキップはMetricsに存在するが`job_tasks.skipped_count`と一致しない場合がある（重複加算禁止）。Metrics未存在・途中のsiteは未確定と表示。
- `grant_result`は`(site, work_id, resource)`の最新結果が1件となるよう集約し、CUI `GrantOnlyReport`と同等に作品名/Resource/ステータス/理由を出す。**消費確認と取得・後処理成功は別軸**。チケット消費確認後に保存失敗したケースは成功扱いしない。`None`消費状態はunknownのまま。
- DiscoverについてはGUIの`execution_worker._run()`から`_discover_target()`の観測結果を `discovery_result` event（既存eventの`payload`使用、DB schema変更不要）に保存し、CUIの`_print_discovery_result`と同等項目をstdoutにもflushする。対象keyの失敗時は`candidate_finished failed`（key明示）を残し既存のfail-stop契約を維持。結果の集約は`observed/new/known/complete/stopped_reason/warnings`。数字は観測結果からのみ、欠落した数字はunknown。
- 開始前に失敗してMetricsもEventsもない場合、ジョブ失敗は表示しつつ「内訳未取得」とする。標準ログ・stderrにある診断をサマリの仮計数に使わない。

### 2.3 リアルタイム通知/状態の所有

- `MainWindow._job_poll_timer`と既存`JobController.poll()`を唯一のsupervisorとして再利用。monitorにも同じpoll後の状態を渡す。新たなworkerや別スレッドでDB stateを書かない。GUI threadでWidget更新、ログreaderはbounded fast path（負荷が出るならread処理のみ非同期化）。
- `JobsPage`はログviewer/reducerを共有するが、Queue操作のControllerは既存単一instanceを参照し独立起動させない。
- redrawはデータが増減したときのみ。モニターを閲覧中に`setPlainText()`で本文全置換しない。履歴画面にも同じscroll規則適用。

## 3. 非対象と設計判断

- 既存上部のGUI再設計、作品一覧の列・並び・検索、ショートカット・テーマの全面刷新をしない。
- Crawler/Site Policy/Catalog/Watcher/archive生成/Quota更新の業務処理・選択scope変更なし。
- 新規Catalog schema / Management schema移行、stderr/stdout統合書換え、CUIログの文字列regex解析、Siteごと新規特殊UIは作らない。
- CUIコマンドを`subprocess`で二重起動しない。GUIで実際に呼ぶ処理の結果を補完して共有する。
- UIの「実行結果をコピー」など補助操作は必要なら後続。最低限「ログファイルを開く」「コピー」「エラー位置の参照」が使えること。
- warning/errorの分類がソースにない場合、未分類として出す。推測でwarningの重要度を割当てない。

## 4. 実施順 / 停止ゲート

1. [01-console-tail/README.md](01-console-tail/README.md) — raw log閲覧基盤、子プロセスbuffering、DiscoverのCUI parity、Qt-free tests。**ログを読めることが次Phaseのゲート**。
2. [02-docked-monitor/README.md](02-docked-monitor/README.md) — 現行GUI構造維持、下部monitorの組込み、scroll/follow、job選択と更新。
3. [03-result-summary/README.md](03-result-summary/README.md) — 構造化ProgressとAction別サマリのaggregation、Unknown/partialを安全に扱う。
4. [04-history-and-qa/README.md](04-history-and-qa/README.md) — JobsPage共通化、負荷・回帰・Windows検証、docs更新。

各PhaseにLead/Implementer/Reviewerの独立役割。実装レビューは必ず「見た目」より安全性、重複計数、スクロール、回帰、機密漏洩、UI性能を優先。合否・テストと未実施項目は[PROGRESS.md](PROGRESS.md)へ記録。UIの実機レビュー（Windows）で止め、これを契機にP4/P5やSite Adapterを実装しない。
