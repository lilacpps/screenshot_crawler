# P1 — Read-only Windows GUIの実装・検証

> **Status: COMPLETE — USER UI REVIEW REQUIRED; see ../PROGRESS.md**
>
> **Prerequisites:** [main runbook](../README.md) と [P0 contract](../00-design/README.md) を満たし、`PROGRESS.md`にP0の決定・Reviewer結果を記録済みであること。
>
> **Stop condition:** P1完了後は **USER UI REVIEW REQUIRED**。P2以降へ進まない。

## 1. Objective / Completion definition

PySide6のWindowsネイティブGUIを起動し、実Catalog v7 + Watchlistを読み取り専用で扱い、サイト別／作品別の3階層ツリー、情報集計、右ペインのItem詳細、検索/絞り込み/ソート、site/work/key選択を操作できる。**P1でCrawlerを実行しない。**

### Deliverables

- `screenshot-crawler-gui`（または同等の明示的GUI専用コマンド）と`python -m screenshot_crawler.gui`相当の起動導線。
- インストール説明: `pip install -e ".[gui,dev]"` の例（正確なコマンドは実装に合わせ検証）。
- Qt非依存`InventoryService`, read-only Catalog Reader, immutable snapshot DTO。
- PySide6 MainWindow, hierarchical Model, DetailPane, filter/sort, check selection。
- Synthetic SQLite v7/Watchlist fixtureとunit/Qt offscreen smoke test。
- UIレイアウトのスクリーンショット（サイト別・作品別・Work詳細/話数詳細の最低3状態）とレビュー用起動手順。Windows環境で実行できない場合はその事実を明記し、提供可能な代替検証を残す。
- `PROGRESS.md`を更新し、テスト/レビュー/未確認範囲を記録。

## 2. P1.1 — InventoryService / Readerを先に実装

- P0 DTO設計を基にSnapshot構築を実装する。Qtへの依存は禁止。
- Watchlistを一度読み、Catalog v7を一貫した`mode=ro`読取transactionでbulk読み込み。同期状態とWork/key対応関係を検査。N+1 queryの多用を避ける。
- 使用するCatalogの全テーブル: works/items/sources/source_targets。必要なacquisition_scope_sync / inventory evidence / quota_resource_states / crawl_runs / artifactsは一括またはdetails lazy readで取得する。
- DBが存在しない/スキーマ不正/ロック競合などは明示的`InventoryLoadError`を返し、新規作成も自動migrateも行わない。
- Sourceの`acquisition_enabled`/Item`status`/SitePolicy評価を非破壊集計。`completed`と`external`は区別。担当外は詳細に保持。
- site/work/keyの同じDTOを両ビューで投影し、同一item数を不用意に二重計上しない。アクセスモード`paid`でもレンタル中等の`direct`は直取に分類。unknown/unsupportedは分離。
- site共通Quotaの消費可能数は候補話数と別。Work ticketはsite別概要とwork詳細でローカル推定と表示。根拠なき“今すぐ可能”は禁じる。
- Source URLの存在・Archive pathの文字列などは安全な読み取りだけ。URLへアクセスせず、Archive内容を展開しない。
- Snapshotの`loaded_at`、評価に使った`now`、読取Catalog/Watchlistのパス、データ件数などをログや画面に含める（秘密情報を出力しない）。
- P1は原則、カタログの読み込み失敗を“空の一覧”として成功表示しない。

### P1.1 tests

- 正常v7の全テーブル読み込み・不変条件・unknown/null・schema旧版拒否・無いDB拒否・不正Watchlist拒否。
- Work 1つに複数サイト＋複数key。無効keyも構造/取得番号に残る。
- Work/keyがWatchlistにありCatalog未登録、SourceがCatalogにありWatchlistからkey削除、Site/Work identity不一致を正しく明示。
- pending/free, quota, paid, unknown, owned, active grant, expired grant, unavailable, free_until期限切れの分類。
- site共通quotaを複数workの候補数に誤って二重加算しない。
- Itemが複数Sourceを持つエッジケース: 曖昧さを隠さず件数invariantを維持。
- Scope同期stale / missing/evidence欠落/担当外でも失敗履歴を保持。
- `watchlist.yaml`、`catalog.sqlite`、ZIP/statusのhash/mtime前後差分を測りGUI経由の読み取りが書き込まないこと。

## 3. P1.2 — MainWindow / Qt TreeView

Qt標準部品を利用。大きな自前描画やQMLは不要。

### 画面の要件

- 初期推奨サイズ約1400x850、最低サイズを定めてレイアウト破綻させない。
- 上部: `作品管理`、[サイト別 | 作品別]、検索入力、状態フィルタ、再読込、read-only表示。
- 中央左: `QTreeView`+`QAbstractItemModel`でsite→Work→key、Work→site→keyを投影。QSplitterで右詳細と幅を調整。
- 列: 対象名、取得済/対象、直取候補、Quota対象残、有償未取得、状態、最終確認。最初に全列が入らなければ水平スクロール/列幅保存はオプション。
- 右: context-sensitive `DetailPane`。Site/Work/keyクリックによって概要を切替。keyではItem一覧を表形式で表示しItemクリックで詳細表示。
- 下部: `N key選択中`、選択解除とDiscover/Batch/Grant-onlyの無効ボタン。将来拡張のためインターフェースを綺麗に分ける。

### Selection/state

- `checked_keys` setと`focused_node`を別状態にする。クリックで詳細、checkboxで選択、展開矢印で展開。親は3状態チェック。
- site/workのcheckboxは配下の**全key**に作用する（検索で隠れた子も含む）。一部選択の中間状態を正しく出す。
- 検索・Filter/Sort・view切替・再読込の前後でchecked key setは維持。もう存在しないkeyは安全に除外して通知。非表示キーは選択を維持し、選択件数に含める。
- 読取時に`enabled=false`のkeyでも選択できるが無効状態の表示は常時行う（後のP2で操作制約を決める）。
- disabled/enabledと`acquisition_enabled`が違う概念であることをtooltip/詳細文言で示す。
- Work階層でkeyをarchive_order順に表示。Site階層でも複数keyの関係が分かるようにする。

### Filter/sort

- 検索はタイトル/Watchlist label/key/site。部分一致、入力ごとのUI反応、祖先保持、クリア。
- Filter「すべて」「直取候補あり」「Quota候補あり」「未取得あり」「要確認」「担当外あり」。
- 数値列は数値ソート、文字列は日本語でも安定ソート。兄弟のソートを行い、親/子の意味的順序を壊さない。
- フィルタによりparentが非表示になっても、元の選択状態/件数は維持。

## 4. P1.3 — 詳細ペイン / 日付 / 対応状態

Site detail:
- key/Work数、取得進捗、直取/Quota/有償の集計、最終アクセス確認、Resourceのローカル概要。
- Site Policyが`resource_state_scope=work`で扱うWork Ticketは、Workごとの再試行候補が集計可能な場合だけ表示。分からなければ「未確認」。

Work detail:
- `work_key`、タイトル、同Workの複数site/key一覧、`archive_order`・Watchlistの`discovery_scope`を一覧表示（URLを話数へ適当に変換せず、根拠がある説明だけ）。
- 担当外の件数、同期状態/障害理由、Workとしての累計（サイト横断コンテンツのdedupeはしない）。

Key detail:
- key/site/label、enabled、scope URL、archive_order、`acquisition_enabled`内外のItem数、無料期限等。
- Item一覧の列: `display_position / 派生archive_position(算出できる場合) / Itemタイトル / status / access_mode / acquisition_enabled / free_until / access_granted_until`。Itemが複数Sourceの場合はSource別の詳細を表示。
- Itemクリック→直近のCrawlRun/result/errorとArchive Artifact state/path。大量のRun/Artifactを毎回ロードしない（選択時に読み込んでもよい）。過去Runの`running`残存を現在実行中と断定しない。

Time contract:
- JST表示、時刻の種類を明記（Last Full proof、Last access check、last crawl run、next local retry estimate）。日付不正/欠損時はunknown。
- 次回GrantはPolicyに計算根拠がある場合だけ値を示す。タイマー常時更新やリアルタイム利用可能表示はP1不要。

## 5. P1.4 — 読込・エラー・パフォーマンス

- 初回ロードと[再読込]はbackground workerでGUIをfreezeさせない。loading indicatorと非操作状態を用意。
- 成功したSnapshotはUI内で保持。読込失敗時は最後の成功snapshotがある場合でも「古い表示」と分かる明示的警告を出す。初回失敗なら空表示 + 診断。
- カタログ不在/旧version、不正Watchlist、サイトPolicy不明、権限/lock/SQLite破損を人間が対処できる文言で表示。エラー文字列を一律`except Exception: pass`などで握りつぶさない。
- 目安: 1,000 key / 10万Sourceの合成fixtureで読込から初期表示まで実測し、UI操作（ビュー切替・検索・展開）が体感で遅くないことを確認。厳格な秒数の契約より計測値とボトルネックをPROGRESSに記録し、必要時だけ最適化。
- 大量のItem/Historyを全ツリーに展開してModelインスタンスを無駄に作らない。右詳細の話数は必要に応じてlazy load。
- PySide6のオブジェクトはGUIスレッドが所有。workerから直接widgetを操作せずSignal/Slot等で通知。
- GUIは閉じられる。読み込み中のcloseに対してworker cleanupが安全。不要なdaemonやプロセスが残らない。

## 6. P1.5 — テスト / 独立レビュー / 導入確認

### Automated tests

- Inventory unit: P1.1に記載した分類マトリクス・読取不変・error handling。
- Qt model unit/offscreen: site/work projection、tri-state selection、parent check、hidden selection、focus independent、filter/sort/reload、長い文字列、空data。
- Local integration: synthetic v7 database+Watchlistを`GUI entrypoint`に渡し、load→site view→work view→Item detail→reloadでnon-mutatingを確認。
- `ruff check`（対象ソース/テスト）、Qt関連/Inventory関連の`pytest`、`docs/TEST_STRATEGY.md`に沿うaffected testsを実行。
- 既存Catalog/Batch/Core/SiteAdapterへ変更が及ばないなら、フルpytestは必須ではない。共有APIを変更したならCatalog/Batch/Scope付近のaffected testsを追加し、影響が広ければfull suiteを推奨。
- CI/一般環境でQt起動できない場合は`QT_QPA_PLATFORM=offscreen`を使ったテストを用意。Linux offscreenのみでWindowsでの見た目を「実機検証済み」とは言わない。
- 実サイト、Chrome、quota・ticket、課金処理、ZIP renameを使ったlive verificationは **不要かつ禁止**（P1は閲覧のみ）。

### Visual QA

- Windowsで起動できる環境がある場合、サイト別、作品別、Work詳細、Item詳細のスクリーンショットを撮りPROGRESSに相対パスを記載。画像は個人情報/秘密を含まない合成データを使う。環境がない場合は「Windows実機未確認」と明記。
- 実データの最も長い作品名、同work_key複数サイト/複数key、キー数の多いサイトで列見切れ/スクロール/操作を確認。
- 画面の選択状態と詳細表示が混ざらないこと、視認性の高い未同期Warning、disabled keyと担当外Sourceの区別を確認。
- 異常系としてCatalogが更新された直後/読込失敗/DBファイルなし/読取権限なしでアプリが安全に表示できることを確認。

### Independent review

最終レビューでは次を重点チェックする:
1. 偽の成功/ゼロ表示（missing Work、scope stale、Policy error）を出していないか。
2. 曖昧なItem合算/サイト共通quotaの二重加算がないか。
3. Catalog/Watchlist/ZIPへの書き込みが一切ないか。
4. checkboxが検索・サイト↔作品別の切替で対象を誤って増減させないか。
5. 実行ボタンが有効になっておらず、どのクリックからもCDP接続/CLI起動しないか。
6. PySide6はoptionalで通常CLIに影響を与えないか。
7. Scopeの不一致を単純な`acquisition_enabled`のみで“同期済”と誤表示していないか。

## 7. Exit Conditions / 人間へのhandoff

P1完了の条件:
- 閲覧用GUIが起動し、サイト別/作品別、詳細、フィルタ、チェックをローカル合成データで操作できる。
- catalog v7 + watchlistのread-onlyロードがテストで検証済み。
- user-visibleの数値に区分ラベル/更新時刻/不明理由が付いている。
- UIのP1スクリーンショットと手元での起動コマンドが提示される。
- targeted tests、Qt offscreen smoke、affected tests/ruff、独立レビュー結果を`PROGRESS.md`に記録。
- **P2は未実装のまま停止**。最終報告は「Windows上でGUIを起動し、一覧の列幅、情報量、詳細レイアウト、チェック操作をご確認ください」で終える。
