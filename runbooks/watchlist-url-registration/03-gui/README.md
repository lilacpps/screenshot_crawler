# Stage 03 — GUI一括URL入力・解析結果編集

> Status: COMPLETE。検証は ../PROGRESS.md のStage 03 checkpoint。永続保存なし。

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

## Stage 00後の決定: 手動登録のUI

- URL状態（valid/converted/blocked）とnative work identity/titleの証拠（verified/observed/unknown）、registration state（needs_manual_confirmation/ready/needs_scope/blocked）を別々に表示する。URL validだけでは保存準備OKと見せない。
- 正規URLを確定できたがID/titleが不明なら作品名labelの入力・既存/新規Workの指定・ローマ字key/work_keyの修正と人の明示確認を提供する。手動確認はidentityをverifiedに変更しない。不正/未対応URLには手動登録bypassを出さない。
- 完全一覧previewは既存4サイト（magapoke/jumpplus/zeblack/comicdays）で先行。他7サイトを含む複数keyのscope詳細編集には「未対応」を理由付き表示する。
- Tests: 作品名手入力/確認、confirmed draftとunknown identityの両立、blocked URLでは確認無効、再解析による確認失効、未対応previewの案内、GUI非同期操作とno-write。
