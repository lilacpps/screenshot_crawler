# Phase 01 — Consoleログ取得・CUI同等性

## Starting evidence
- `JobController.start_job()` は`Popen(... stdout=PIPE, stderr=PIPE, text=True)`、`_copy_log()`でsanitize+flush済み。既存 `stdout.log`/`stderr.log` を壊さない。
- GUI Discoverは `_discover_target()` を直接呼ぶため、CUI `_print_discovery_result()` の観測結果情報が欠ける。

## Objective / 変更範囲
1. Qt依存しない小さな`LogTailReader`（推奨 `management/log_tail.py`）を追加。`job_id`と`stdout|stderr`から固定log pathを求め、stream毎にbyte offsetとincremental UTF-8 decodeを保持。初回/切替/追加/ファイル不在/末尾の不完全UTF8/truncateを扱う。
2. 子workerのみunbuffered起動にしてログ遅延を解消。 `_copy_log`のsanitize, flush, error fail-closedは不変。
3. GUI Discover実行ループで処理結果の数値をCUI形式で出力。全キー終了・中断・例外時の構造化`discovery_result`と`candidate_finished`を出せる範囲で追加。事実が取れていない例外を偽の0件結果にしない。`_print_discovery_result`のロジックが使えるなら再利用、循環依存に注意。
4. 異なるstdout/stderrを厳密な順序で混ぜず両ストリームへのアクセスを保証。既存logs rootとファイル名を維持。

## Constraints
- Discoveryの失敗停止/候補選択/disable判定は変更しない。
- 読み込み最大bytes/tick、history初回tail上限、view可視行数に上限。ログ原本ファイルの削除・切詰め禁止。
- `-u`起動時の子worker command array, start gate, credentials redaction, lease/heartbeatを維持。
- Qt/Crawlerサイトへの接続をテスト要件にしない。

## Tests
- `tests/unit/test_management_log_tail.py`: 追記、file not yet created、UTF-8 multibyte chunk分割、CRLF、長文、大量ログ、truncate、stream切替、過去ログtail省略明示、二重読み込み/欠落なし。
- `tests/unit/test_management_jobs.py`: fake workerのunbuffered引数/環境、stdout/stderr両方キャプチャ、sanitize維持、ログsink failure fail-stop。
- GUI経由Discover（mock adapter）と通常CUIの観測数・新規数・既知数・停止理由・warnが意味的に一致、例外時key明示。実ブラウザ接続禁止。
- Ruffと関連CLI regression tests。

## Acceptance / Exit
- 実行中のログが追記される、標準エラーが落ちない、GUI DiscoverにCUI相当の情報が現れることをfake jobで証明。
- 既存P2/P3の安全ガードを維持し、`PROGRESS.md`へCommit/合否・留保を記録したらPhase02へ。
