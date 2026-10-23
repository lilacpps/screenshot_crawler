# Windows 作品管理GUI（P1・閲覧専用）

Python 3.12以上とPySide6を使うローカルアプリです。Catalog v7とWatchlistを
読み取り専用で表示します。P1完了後は **USER UI REVIEW REQUIRED** です。

## インストール・起動

リポジトリのルートで実行します。既存CLIだけを利用する場合、gui extraは不要です。

```powershell
python -m pip install -e ".[gui,dev]"
screenshot-crawler-gui --catalog catalog.sqlite --watchlist watchlist.yaml --runtime crawler.yaml
```

この作業環境の既存`.venv`にはインストール済みです。直接起動できます。

```powershell
.\.venv\Scripts\python.exe -m screenshot_crawler.gui --catalog catalog.sqlite --watchlist watchlist.yaml
```

pipのないuv環境では `uv pip install --python .venv/Scripts/python.exe -e ".[gui,dev]"`
を使えます。起動引数を省略するとルートのcatalog.sqlite/watchlist.yaml/crawler.yamlを
参照します。存在しないCatalogや旧スキーマを自動作成・移行しません。

## 合成データでレビュー

生成ツールだけが、明示指定した**新しいディレクトリ**にサンプルを作成します。
実行のたびに未使用の出力先を指定してください。GUIからは呼び出しません。

```powershell
.\.venv\Scripts\python.exe tools/gui_sample.py --output .tmp/gui-review
.\.venv\Scripts\python.exe -m screenshot_crawler.gui --catalog .tmp/gui-review/sample.sqlite --watchlist .tmp/gui-review/sample-watchlist.yaml --runtime .tmp/gui-review/sample-runtime.yaml
```

同じ作品に4サイト、取得済・外部取得・skipped・未取得、無効key、担当外Source、
未Discover、未管理、Scope未同期を含みます。実在する作品・認証情報・個人情報は
含みません。Artifactのパスは説明用で、対応するZIPは作成しません。

## 操作と値の読み方

- サイト別と作品別を切り替えます。チェックはWatchlist key単位で保持します。
  詳細表示用の行クリックとは独立しています。親チェックは検索で隠れたkeyも含みます。
- 検索・状態フィルタ・列ソート・階層の展開と折りたたみを利用できます。
  右ペインとの境界はドラッグで調整できます。
- サイト、作品、keyを選ぶと詳細が変わり、keyの話数行を選ぶとItemの直近CrawlRunと
  Artifact/保存先を確認できます。保存先の存在確認・ZIPの展開は行いません。
- 「取得済」はcompletedのみです。externalとskippedは別内訳です。
  対象総数は担当内Sourceを持つItem数、担当外はSource数です。
- 「直取候補」「Quota対象残」はCatalogと既存Site Policyによるローカル判定です。
  Quotaの対象話数とサイト共通の残枠は別です。実サイトの現在の取得可否を保証しません。
- `—`は未確認・算定不能、`~`は未同期などの診断がある暫定集計です。
  未Discover・Scope未同期・未管理は正常な0件に置き換えません。
- 完全Inventory証拠の日時とアクセス観測日時は別です。再試行時刻は既存Policyと
  消費記録・設定に根拠がある場合だけ表示します。値は再読込時に更新されます。
- WatchlistのDiscovery無効とSourceの担当外は別概念です。無効keyもチェックできます。

## P1の制約

Discover / Batch Run / Grant-onlyは無効です。Crawler、Chrome/CDP、外部サイトには
接続しません。Catalog・Watchlist・ZIP・status JSON・metricsを変更しません。
ジョブ、スケジューラ、Watchlist編集、Scope apply、Renameは未実装です。

直近履歴はItemごとの最大Run ID、ArtifactはItem/種別/形式/backendごとの最新記録です。
過去のrunning記録を現在実行中とは判断しません。物理ファイル検証はしません。
異サイト間の同じ内容の話数を自動統合しません。未同期時の派生archive位置は不明です。

WAL形式のCatalogはP1ではエラーにします。SQLiteはread-only接続でも`-shm`を
更新し得るため、完全な非変更を優先しています。運用側で明示的に作成した一貫した
通常journal形式のバックアップを選んでください。GUIはcheckpointやjournal変更を
行いません。通常のCatalogServiceはWAL設定を要求していません。

設計は[GUI_INVENTORY.md](GUI_INVENTORY.md)、測定・テスト・独立レビュー結果は
[PROGRESS](../runbooks/gui-inventory-p1/PROGRESS.md)を参照してください。
10万SourceのWindows非同期読込の測定は[性能結果](gui-performance.json)にあります。
初期ロード約3.9秒、表示切替約53ms、検索約32msでした。ロード中には最大約0.58秒の
タイマー遅延があり、大量データの初期処理に短い待ちが生じます。

## レビュー画面

サンプルで生成した画面です。PNGは認証情報を含みません。

- [サイト別](gui-screenshots/site.png)
- [作品別](gui-screenshots/work.png)
- [作品詳細](gui-screenshots/work-detail.png)
- [話数詳細](gui-screenshots/item-detail.png)

Windows上でGUIを起動し、一覧の列幅、情報量、詳細レイアウト、チェック操作をご確認ください。
