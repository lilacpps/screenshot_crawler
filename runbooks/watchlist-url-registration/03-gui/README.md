# Stage 03 — GUI一括URL入力・解析結果編集

> Status: NOT STARTED。Stage 02のdraft APIを利用。原則このStageでは永続保存しない。

## Objective

- MainWindowに「URLから登録」を追加。既存Inventory/Watchlist管理、Discover/Batch/Grant-only、実行モニターの上部UIと選択集合の意味を維持。
- 1件も複数件も改行貼り付けで処理。解析はbackground worker、最大同時数・timeoutをboundedにし、GUI event loopを止めない。異site同時browser操作は既存Browser Session制約を尊重。
- 行ごとに valid / converted / blocked、作品名、input URL→Discovery URL、理由と修正例、重複/既存登録を表示。失敗URLだけ再試行し、他の手動修正とグループを保持。
- Work groupingと既存Work選択、human-readable key/work_key、ラベルを編集できる。キー衝突、未確定タイトルやwork identity、scope未設定をインライン表示。
- Work単位の登録対象check、cancel/back、dirty confirmation、未保存draftの保持。WorkEditorが必要な対象を明示し、単一keyにも任意詳細ボタン。
- 解析エラーやCDP未起動時、待ち受けworker失敗がWatchlistの変更に見えないこと。実ページのreader操作をしない。

## Tests / exit

- Qt offscreen/synthetic/worker tests: single/multi paste、site status、retry、partial failure、edit persistence、group selection、dirty/cancel、large list/scroll、busy/CDP failure、no-write、Inventory selection独立。
- このStageでは保存ボタンは無効または後続Stage未実装を明示し、誤って既存保存処理へ落とさない。
- 検証用一時filesのみ。既存GUI snapshot/monitor変更は必要最小限。
