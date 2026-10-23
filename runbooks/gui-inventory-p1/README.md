# Windows GUI / 作品管理 — P0・P1 実装Runbook

> **Status: PLANNED / NOT IMPLEMENTED** (2026-10-23)
>
> **Scope: P0 設計固定 → P1 閲覧専用GUI実装 → 人間によるUIレビューで停止**
>
> UI確定前に P2（実際のDiscover / Batch / grant-only実行）、P3（ジョブ履歴・スケジューラ）、P4（Watchlist編集・Scope Sync apply）、P5（Rename等）へ進まない。

## 0. 目的

`screenshot_crawler` の管理コストを減らすため、Windowsで実Catalog v7/Watchlistを **読み取り専用** で参照するGUIを作る。サイト別にも作品別にも、各Work / Watchlist keyの取得状況を一覧できること、クリックで話数・取得履歴を読めること、後続実装のためにサイト・作品・keyをチェック選択できることがP1の目的。

サイトと作品の一覧性・大量選択・検索・詳細表示の操作感を、**実データを読み込める起動可能なGUI** で検証する。画面レイアウトを先回りして固定しすぎないが、基礎となる表示分類・データ責務・操作契約は本runbookで定める。

- 技術: Python 3.12+ / Windows 10・11 / PySide6（`gui` optional extra）。
- ローカルアプリ。初期版にFastAPI、Webフロントエンド、常駐daemon、job queue、management.sqlite、マルチユーザー認証は不要。
- read-only最優先。メイン画面のDiscover / Batch Run / Grant-onlyはP1で **無効なプレースホルダー** にする。CLI実行を隠れて呼ばない。
- GUIは既存Catalog/Watchlist/Policyを参照するだけ。Catalog schema、Discovery、Batch、Core、Site Adapter、ZIP命名の現在の挙動を変更しない。
- `work_key`は人手でまとめる作品単位。別サイトのItemを自動mergeしない。`key` はWatchlist上の取得範囲、`site` は取得元。`acquisition_enabled=0` のSourceも履歴確認のため残して表示。

## 1. 先に読むもの / 現行実装に関する確認

Authority: `AGENTS.md` → `docs/SPEC.md` / `docs/ARCHITECTURE.md` / `docs/DISCOVERY_AND_BATCH.md` / `docs/BOUNDED_DISCOVERY.md` / `docs/ACCESS_CONTROL_AND_PACING.md` / `docs/TEST_STRATEGY.md` / `docs/CODEX_IMPLEMENTATION_GUIDE.md` → 実コード/テスト → `note/`。命名・担当範囲は `runbooks/work-key-archive-order/README.md` / `PROGRESS.md` と実装を参照。

2026-10-23 mainで確認した状況（着手時に再検証）:

- `src/screenshot_crawler/catalog/schema.py` はv7。`works/items/sources/source_targets/crawl_runs/artifacts/quota_resource_states/acquisition_scope_sync/discovery_inventory_evidence/discovery_inventory_positions` がある。
- `src/screenshot_crawler/watchlist/models.py` は `key/work_key/site/url/label/enabled/discovery_scope/archive_order` を持つ。
- `src/screenshot_crawler/watchlist/reconcile.py` の `ScopeReconciler.preview` と `require_synchronized` は状態参照の候補。`apply` をGUIで使ってはいけない。
- `src/screenshot_crawler/site_policies/*` がaccess評価、Resource/Grantの意味を持つ。汎用フロントにsite名ごとのアクセス判断を複製しない。
- `src/screenshot_crawler/batch/planner.py` は既存のsite単位Plan。P1一覧の合計は「現在のサイトBatchで実行される正確な件数」ではない。
- `CatalogService.read_works_items_sources_and_targets` は_read_only_connection使用。一方`list_crawl_runs`/`list_artifacts` は通常接続を使うため、P1で無条件に呼ばない。必要なら専用の統合read-onlyクエリを追加。
- `_read_only_connection` は`mode=ro`。既存スキーマ不一致/不在は画面上でエラーとし、新規作成・自動migrateしない。
- v7のScope同期済情報とWatchlist設定がずれている場合、正常な取得対象として断定しない。
- Qt GUIは現時点で未実装。`pyproject.toml` の既定依存にPySide6はない。

`runbooks/README.md` の規約に従い、本ディレクトリを作業単位とする。詳細は `00-design/README.md`、`01-readonly-gui/README.md`、進捗は `PROGRESS.md`。

## 2. P1の機能境界

| 機能 | P1 |
|---|---|
| WindowsのGUI起動、CatalogとWatchlistパス指定、読み取り専用リロード | 必須 |
| サイト別／作品別の3階層ツリー表 | 必須 |
| Work / Site / keyの取得状況集計、正常・不明・要同期の明示 | 必須 |
| 作品・サイト・keyの検索、フィルタ、ソート、折りたたみ | 必須 |
| checkboxによるsite/work/keyの選択、ビュー切替でも保持 | 必須 |
| 右詳細ペイン: Site / Work / key / Item情報、話数一覧 | 必須 |
| SiteのQuota/Grant概要、key/Work詳細のローカル再試行情報 | 利用可能な根拠の範囲で表示。未確定値は不明 |
| 既存のCrawlRun/Artifactをread-only参照 | 必須（詳細表示時でも可） |
| Discover / Batch Run / grant-only / planの実行 | **実装禁止。ボタンは無効** |
| Schedule、JobService、Job DB、Watchlist編集、Scope apply、rename | **対象外** |
| 起動時にChrome CDPへ接続、Live availability収集、実サイト操作 | **実装禁止** |

## 3. UIデザイン契約

### 3.1 レイアウト（1400×850px程度での利用を基準。実サイズはリサイズ可能）

```text
┌─ Screenshot Crawler ───────────────────────────────────────────────────┐
│ 作品管理 [将来:履歴] [将来:スケジュール]     Catalog v7 ● 読み取り専用 │
│ [サイト別 | 作品別]  [検索_________________] [状態フィルタ] [再読込] │
├───────────────────────────────────────┬───────────────────────────────┤
│ 対象                       取得済 直取 Quota 有償 状態 │ 詳細ペイン   │
│ ▾ □ ゼブラック             85/120  3    22    7  正常 │ Site概要     │
│   ▾ □ ふつうの軽音部       57/72   2    11    2  正常 │ Quota/Grant  │
│     □ 範囲: 第31〜102話    57/72   2    11    2  正常 │ ...          │
│ ▾ □ ジャンプ+              ...                           │ Work詳細     │
│   ▾ □ ふつうの軽音部       ...                           │ key一覧      │
│     □ 範囲: 第122話〜      ...                           │ 話数テーブル │
├───────────────────────────────────────┴───────────────────────────────┤
│ 選択中: N keys [選択解除]              [Discover][Batch][Grant-only] │
│                                        （P1ではボタン無効）          │
└───────────────────────────────────────────────────────────────────────┘
```

上記の数字は説明用であり実データを意味しない。

- 左70%前後に`QTreeView`、右30%前後に詳細ペイン。`QSplitter`で幅変更・右ペインの折りたたみを可能にする。
- 標準列: 対象、取得済/対象、直取候補、Quota対象残、有償未取得、状態、最終確認（幅が厳しければ任意列を非表示/横スクロール）。
- 実データにkeyが存在するサイトは、対象ゼロであっても0と不明を区別する。未登録サイトの「0」は未登録の意味でありサイト全体の配信数ではない。
- 最下部にチェックされたkey数を常時表示。実行系ボタンはグレーアウト、ツールチップに「P2で対応」。
- 高DPI、Windows日本語、長いタイトル、ゼロ件、スクロール時の表示崩れを考慮。凝った独自描画より標準Qt widgetを優先。

### 3.2 階層・選択・フォーカス

同じkey集合を異なる投影で表示する:

- サイト別: `site → work_key → Watchlist key`
- 作品別: `work_key → site → Watchlist key`
- parentクリックは展開/詳細表示、checkboxクリックは選択、keyタイトルクリックは詳細表示。展開ボタンとcheckboxは別。
- keyのStable identityは`WatchlistTarget.key`。Qtの行番号、Work ID、表示名は選択IDにしない。
- parent checkboxは子keyの選択を制御し、一部選択ならQtのpartially checked。両方のビューで同じ選択状態を保持。
- フィルタ非表示のkeyも選択状態を保持する。親の選択は**フィルタで見える分だけ**に偶然縮退させない。「表示中を選択」は別機能として後日でもよい。
- `enabled:false`は「通常のDiscover --site / --allから除外」であり担当外ではない。灰色ラベルまたは補足列で表現し、P1のチェック操作自体は許可。P2の手動実行時の動作判断は別途確定する。
- 既存WatchlistにあるがCatalog Work/Sourceがないkeyも、「未Discover」として表示する。CatalogにあるがWatchlistキーに対応しないSourceは、「未管理/所属不明」として確認可能にする。勝手に他keyへ付け替えない。
- Work集約はあくまで同一work_keyの既存Item数の合計。異サイトの同一内容で重複する話数の差引き・巻数換算はしない。
- 詳細ペイン: siteクリック→site集計/Resource概要、workクリック→各site/keyの分担/順序/集計、keyクリック→範囲・Item一覧、Itemクリック→取得/アクセス・CrawlRun/Artifact（子ツリーにItemを増やさず右側で表示）。

### 3.3 検索・フィルタ・ソート

- 検索対象: Work title、Watchlist label、key、site。大文字小文字差を吸収。日本語は部分一致。検索は読み込み済Snapshotに対して行う。
- フィルタ: すべて、直取候補あり、Quota候補あり、未取得あり、要同期/要確認、担当外あり（最小構成は切替式でも可）。
- ツリーの子が一致すれば祖先も見せる。フィルタ中のparent checkboxは非表示子も含む集合を維持する。
- デフォルト順: siteは表示名/registry順、Workはタイトル、keyはarchive_order指定時の昇順・同順位なし、未指定時はWatchlist登場順。取得話数はdisplay_positionの昇順。
- 列ソートはその階層の兄弟に限る。ソートしてもkey選択/詳細フォーカスは変わらない。
- フォーカス（詳細表示）とチェックされた実行対象の集合を別stateにする。

## 4. 値の定義・出典と不明表示

P1は「Catalogに最後に保存された事実」と「Site Policyからのローカル評価」を分けて表示する。実サイトの現在の在庫/アクセス可否を保証する表現は禁止。

### 4.1 計数の基準

1. Watchlist key / site / Work の所属関係は`Watchlist`＋Catalog `Source.discovery_key`・Work外部キーに従う。
2. 担当範囲内: `Source.acquisition_enabled=1`、担当外: `0`。ただし対象Workの同期が不一致/未証明なら、計数を「確定」と表示せず要確認にする。
3. 同じItemが複数Sourceを持っても、key/Workの「Item総数」「取得済」はItem IDを二重計上しない。Site/keyに複数帰属する曖昧なItemがあれば明示的warningにし、合計値の意味を明記する。
4. `completed`=Crawler取得済、`external`=外部取得済、`skipped`=意図的除外。3つを混ぜて「取得済」と呼ばない。`pending`のみ取得候補として分類。
5. pendingかつ担当内Sourceをsite-local Policyに渡し、`direct`（新規quota消費不要）、`quota`（resourceを必要とするプール）、`paid`（追加支払いを要する既知アクセス）、`unavailable`、`unknown/unsupported`等へ分類。各Itemは一つの主要カテゴリにのみ計上。`access_granted_until`有効でdirect扱いされるpaid/quota Sourceを有償数・Quota数へ二重計上しない。
6. SitePolicy評価に必要なsite共通残quotaはそのsiteの **全Source** を使う。総Quota対象残と「現時点で使える枠」は別表示。`grant-only`の候補数は通常のQuota候補数と同義ではない。
7. Site Policyにより別resourceで選択できるSource（例: Magapoke work_ticket/premium_ticket）は話数を重複計上せず、詳細にresource種別を表示できるよう拡張可能なモデルにする。
8. 予期しないPolicyエラー、未対応access_mode、最新情報不明、scope不一致を「0件」として飲み込まない。状態欄と詳細にreasonを出す。

集計モデル例: `total_assigned`, `crawler_completed`, `external`, `skipped`, `pending_direct`, `pending_quota_pool`, `pending_paid`, `pending_unavailable`, `pending_unknown`, `out_of_scope`, `status/diagnostics`。`total_assigned` は担当内のItem件数（決してサイト全話数ではない）。明示的不変条件: サマリーの内訳合計は`total_assigned`と一致、所属キー別との合算で二重計上があれば診断に切り分ける。

### 4.2 最終確認とGrant

- `discovery_inventory_evidence.completed_at` はそのkeyの成功した完全Inventory確認日時。**最終Discover実行日時と混同しない**。
- `sources.access_checked_at` / `last_seen_at` は観測の記録。Work/siteでは根拠のある最大日時を「最終アクセス確認」として表示。どの種類の時刻かラベルを付ける。
- Catalogにはまだ全Discoverジョブ履歴がないので「前回Incremental実行成功時刻」を推定で埋めない。
- Site Policyの`supported_access_resources / grant_only_supported_access_resources / available_quota / grant_only_retry_at / grant_only_skip_reason / resource_state_scope` と`quota_resource_states`等を使用。**実サイトの使用可能枠ではなくローカル判定**。
- Site行にはResourceの概要（work ticketなら再試行候補Work数・既知の最短試行時刻、site共通quotaならsite共通枠）を詳細ペインに表示。Work/key詳細は根拠のある場合に個別の次回試行時刻を表示。Policy APIで安全に導けない場合は「不明/実サイト確認要」。
- 単純に前回使用時刻＋23hを汎用GUIで計算する等、Site Policyを迂回したsite固有知識の複製は禁止。

### 4.3 運用状態 / blocker

- `Scope同期済 / 要同期 / 未Discover / 未管理 / 計算不能`を区別。既存`ScopeReconciler.preview` や同期情報で非破壊的に判定。`apply`禁止。
- policy-local eligible数と現在のBatch Plan candidate数の差（quota枠・順序・外部状態・deferred resolver）があるため、列名は「直取候補」「Quota対象残」。正確な実行候補件数はP2実行確認時にPlannerで再計算する。
- 不明な場合はdash（—）+ tooltip/理由表示。赤/緑の色だけに依存せず文字表示を併用。
- 履歴詳細のCrawlRun（成功/失敗）とArtifact（状態/locator）はDB記録。P1初期ロードで全ZIPをstatしない。必要な時だけ存在有無をread-only確認できる方式でもよい。

## 5. アーキテクチャ / 読み取り専用境界

```text
PySide6 MainWindow
 ├─ Toolbar (view/search/filter/reload)
 ├─ InventoryTreeModel + FilterSortProxy (site/work/key)
 ├─ SelectionState (set[key], focused_id)
 └─ DetailPane (site/work/key/item)
           │
       InventoryService  [pure read/derive]
           │
   ┌───────┼───────────────┐
 Watchlist Reader   CatalogInventoryReader (SQLite RO)   SitePolicy Registry
                      │
                 Catalog v7
```

推奨実装:
- `src/screenshot_crawler/management/inventory.py` 等にQt非依存のDTO/集計サービスを置く。
- `src/screenshot_crawler/gui/` にQt依存Model/View/Controller。`gui` extraにPySide6を追加し、通常CLIの依存を増やさない。
- `screenshot-crawler-gui` scriptまたは `python -m screenshot_crawler.gui` を起動手段とする。PySide6未導入時のエラーはGUI導入案内を返し、CLI起動を壊さない。
- Catalog全体の`works/items/sources/source_targets/sync/evidence/必要なquota state`を **一貫したread-onlyトランザクション** で読み出す（新しい専用Reader/API追加は許可）。現行`list_crawl_runs/list_artifacts`は書き込み可能接続経由のため、GUI専用Readerを使用する。
- SQLiteは`mode=ro`（必要なら`PRAGMA query_only=ON`）。DBパスがなければ即エラー、sqliteを作成/初期化/移行しない。Watchlistパス不在・不正も明示エラー。
- 読み込み処理はworkerスレッド/`QThreadPool`等へ分離。UIスレッドから大量DB query、Site Policy評価、各WorkのScope previewを直列で反復しない。計算量と呼び出し回数を測定。
- 初回は一つのInventorySnapshotを保持。View切替/検索/選択はメモリ内。`再読込`では新Snapshotに原子的に置き換え、既存選択keyを存在するものだけ保持し、消えたkeyを報告。
- P1でネットワーク通信、Chrome接続、サイトへのアクセス、ZIP変更、CLI実行、Watchlist書込み、Scope apply、SQLiteにスキーマ作成は行わない。
- GUIの設定（ウィンドウ幅/最後の閲覧パスなど）を永続化するなら独立したUI専用場所とする。**Catalog、Watchlist、Books配下にUI設定を書かない**。初期版では永続化自体を省略可。
- 将来P2はGUIのチェック済key集合を渡す専用JobServiceを追加する。今はそのインターフェース（`selected_key_ids`等）を想定するだけで、ジョブDB/プロセス実行は作らない。

## 6. 調査・実装フェーズ

- [P0 — inventory/UI contract確定](00-design/README.md): 現行データ境界の実証、数値分類・同一Item重複処理、wireframe、Qtのモデル・選択契約、targeted fixture/受け入れ条件を固める。GUIコード本体はこのGateではまだ作らない。
- [P1 — read-only Windows GUI](01-readonly-gui/README.md): 実Catalog閲覧、ツリー、詳細、検索、チェック、読み取り専用/例外・高DPI・UI verificationまで。
- `PROGRESS.md` に各Gateのコード/テスト/レビュー/残課題とUIレビュー待ちを記録する。

**P1完了で作業を止める**。実利用者がGUIを操作してレイアウトをレビューする前にP2へ移行しない。

## 7. フェーズ共通の品質・安全契約

- Develop on a feature branch; never modify operational `catalog.sqlite`、`watchlist.yaml`、`output/Books`、`output/crawl-status`、`output/metrics` in tests. Use isolated fixtures; actual data useはread-onlyに限定。
- GUI起動、検索、reload、policy評価、詳細表示でソースDB・Watchlistのhash/mtime、Artifact locator等が変更されないことを検査。設定保存は別場所。
- Site PolicyをGUI内で複製しない。評価は1回の固定now（JST-aware）を使い、画面上で時間が変わり得る表示は再読込で更新。
- Test hierarchy/filter (child matched→parents displayed), tri-state check, selection preserved across view and sorting, disabled key handling, partial Work/site, empty data, long names, unknown key, missing/old schema, sync stale, unknown policy, shared quota, deferred resource, multiple resource, paid-with-active-rental, out-of-scope Source.
- Test UI model and inventory calculation independently. Qt GUI smoke test is offscreen/local; real Windows visual review remains separate。
- P1 completion report: changed files, Qt起動手順, screenshots (site/work and detail), sample counts and caveats, tests/ruff, unanswered UI questions, explicit **USER UI REVIEW REQUIRED**. Do not claim P2 features implemented.

## 8. GUIレビュー時のチェックリスト

完成したWindows P1をユーザーが実操作して、以下を確認する:
1. 実作品数で読み込み・検索・展開・スクロールが快適か。
2. サイト別と作品別で、同じ作品の複数keyが自然にまとまるか。
3. 列幅・文字サイズ・情報密度（取得済/直取/Quota/有償/状態）が適切か。
4. 詳細ペインが右側でよいか、必要なら別画面/下ペインのほうがよいか。
5. checkbox選択と詳細フォーカスを混同しないか。
6. Scope未同期/担当外/不明を正しく見分けられるか。

レビューに基づくUI調整を反映してから、別途P2の実行Job設計を開始する。
