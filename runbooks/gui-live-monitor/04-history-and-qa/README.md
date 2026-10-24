# Phase 04 — 履歴表示共通化・性能・安全回帰

## Starting evidence
- Phase01-03でraw logs/Monitor/summaryが利用可能。
- 現行`JobsPage.refresh()`は500msごとに`list_jobs()`→`_show_selected()`→`setPlainText()`。途中閲覧を壊す。

## Objective
1. `JobsPage`でMonitorと共通のlog viewer/tail readerと`JobResultPresenter`を使用。既存キュー操作・選択ジョブ開始・停止要求・緊急強制終了・再計画の操作と確認文言を保持。
2. 履歴一覧は現在選択のjob_idを保持。更新のたびに全行/ログを無条件に再生成しない。最新EventsはSQL `DESC LIMIT` またはkeysetで取り、先頭500件に閉じ込められないようにする。
3. 同一JobのログをMonitorと履歴で閲覧中、各viewerの選択・scroll状態を独立管理。ジョブがterminalになっても原文/サマリが読める。GUI再起動後も既存ファイル/DBから表示可能。
4. 危険操作、worker identity、redaction、Job queue進行、non-destructive Catalog Preview、ログへのURL/credentialsの扱いを独立レビューする。
5. `docs/GUI_README.md`、必要なら`docs/GUI_INVENTORY.md` とscreen capture docsを更新。P2/P3の既存runbookを書き換えない。

## Tests / Verification
- `tests/unit/test_management_jobs.py` / `tests/unit/test_cli_job_events.py` / CLI affected tests / `tests/integration/test_gui_smoke.py` / 新しいQt offscreen fixtures。
- fake workerでDiscover/Batch/Grant-onlyの一連の`preview → queue → run → monitor → summary → history → rerun preview`。本番Catalog/Watchlist/Books, CDP, real ticketsへのアクセス禁止。
- 大量ログ/Events（少なくとも5万行/ログ数MB）でもUIイベントループが止まらず、Qt viewは上限保持。full fileへのアクセス確保。scroll位置はtail追加とhistory定期refreshで維持。
- Windowsで980×600、1400×850、高DPI、上下サイズ/折畳、操作ボタン、複数job、独立履歴画面の表示確認。Windows未検証なら明確に保留と記録。
- `ruff`、targeted/integration、影響範囲の広い時はfull suite。テスト結果を種類別・実行環境別に`PROGRESS.md`へ記載。
- 独立Reviewerは特にUI以外の副作用、Batch planned skip重複、Grant消費unknown→noへの誤丸め、false success、GUI閉鎖中のworker状態、資格情報漏出を確認。

## Acceptance / Exit
- ユーザーが通常画面のmonitorで進捗→結果→詳細ログを閲覧でき、履歴でも同じログをスクロール固定で読める。
- 上部UIの配置とP2/P3の動作に回帰なし。画面キャプチャとレビュー結果を残し、ユーザーのWindows実操作レビューで停止。
