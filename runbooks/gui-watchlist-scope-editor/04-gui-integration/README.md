# Stage 04 — Windows GUI統合・保存/反映E2E

> Status: **COMPLETE / REVIEW APPROVED**。Stage00〜04の結果・制約は [PROGRESS.md](../PROGRESS.md) を参照。以下は実行契約。

## UX/変更範囲
`src/screenshot_crawler/gui`配下にWatchlist専用Page/Model/Editorを追加。既存Inventoryページ、実行ボタン、チェック選択、`gui-live-monitor`に変更が入っても**実行画面の配置/用途を維持**。既存`InventorySnapshot`とsite別/work別projectionを再利用できる部分は再利用するが、編集用QAbstractTableModelは実行選択checkboxと別state。

画面:
- ヘッダ「作品管理 / Watchlist管理」、サイト別/作品別切替、検索、[新規key登録]。
- 左：site/work/key階層、同期/未Discover/未管理状態。中央：`enabled`/`label`/`url`とscope境界編集、work内`archive_order`順序一括編集。右：site-native話一覧、チェック、変化する取得担当、取得済/アクセス観測。
- 数百/数千話でも遅くならないModel/Virtual scrolling、全選択・範囲選択・除外2件などの操作。未保存変更・画面切替/再読込確認。active Job中の編集制限/lock状態。編集中の値はYAMLにまだ保存しない。
- [変更プレビュー]：追加/除外/維持、未Catalog/unknown、番号変更の予測とブロッカー、必要なFull/Sync/Renumberを表示。[Watchlist保存]は独立。[Full Discovery]は既存ジョブへ接続して明示実行。[Scope同期プレビュー/適用]は明示確認して最新証拠だけをapply。既存ジョブの詳細・ログを参照できる導線は再利用。
- 「保存済・Full待ち」「Full完了・同期未反映」「同期済み」「反映ブロック（具体理由）」「既存ZIP改名は未実施」を区別。再試行は現行snapshotで再previewする。プレビューを成功保証として固定表示しない。
- 初期URL追加は既存形式を手動入力。siteをURL構造で安全に判定できる場合だけ候補提示（推測でwork_key統合しない）。Chrome起点登録は後続。

## Safety
- Qt UI threadをブロックするサイト通信/DB読込/Full/Syncを禁止、`QThreadPool`等の既存方式を再利用。複数workerからQt Modelを書き換えない。
- 実行監視や保存中にWatchlist pathが切り替われば旧editorを無効化。`expected hash`で保存競合検出。Catalog/Watchlist pairを間違えない。
- GUIの観測/プレビューでは`DiscoveryService`のCatalog書込経路を呼ばない。Scope applyはexisting job lock/CASを利用。適用前に操作内容を具体的に確認する。

## Tests / acceptance
1. `tests/unit/test_gui_model.py`、`tests/integration/test_gui_smoke.py`: site/work切替・キー選択・詳細、dirty保持、複数キー、チェック選択、全解除拒否、scope boundary, `archive_order` 並び替え、stale/未Discover。
2. synthetic listing + temporary Watchlist/CatalogでGUI→プレビュー→設定保存→Full→scope-sync preview/apply→Batch planまでをE2E。保存前no-write、除外話Batch候補ゼロ、取得済みZIP不変、変更した採番表示、競合時apply停止を検証。
3. active jobs / page切替 / legacy UI / gui-live-monitor / Windowsパス / PySide6起動 / 最小ウィンドウ幅・大量話数で操作不能にならない。
4. 原則 `docs/TEST_STRATEGY.md` に従う。必要ならoffscreen Qt smokeとWindows実機・隔離CDP read-onlyのみ。実サイトquota/チケット/有料Viewer消費はテストしない。

## Exit
既存GUI regressionなし、previewにside effectなし、保存/同期の中間状態が復旧可能、差分を独立Reviewerが確認。`docs/GUI_README.md`、`docs/BOUNDED_DISCOVERY.md`、`docs/DISCOVERY_AND_BATCH.md`、`note/00_core.md`/`note/03_magapoke.md`を実際の変更に従い同期し、`PROGRESS.md`に未実施テストと理由を記録する。
