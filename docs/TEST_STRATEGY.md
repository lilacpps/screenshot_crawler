# Test Strategy

## 1. 目的

Core回帰、Browser Session回帰、Site Adapter前提崩壊を分けて検出する。実サイト確認済みの挙動を、根拠なく一般化したロジックで置換しない。

Discovery / Catalog / Batch実装後は、site listing観測、Catalog同期、Batch policy、Crawler実行を分離して検証する。

## 2. Unit Tests

実browser不要のものを対象にする。

- PageState / models
- fingerprint
- Runner guards
- max_pages境界
- duplicate / same-content
- manifest / progress
- output directory safety
- packaging / manifest validation
- Adapter helper / parser / naming
- CDP endpoint resolution
- global endpoint / site override precedence

Discovery / Catalog / Batch実装後:

- Watchlist parse / validation
- Watchlist add/remove/enable/disable
- duplicate watch key rejection
- Catalog schema / migration initialization
- item/source upsert
- external state updateとlocal state preservation
- source identity / URL change
- cross-site duplicate candidate warning
- full sync reconciliation
- incremental known streak
- source priority
- Site Policy quota eligibility
- access grant window

## 3. Browser Session Tests

共通Crawler Chrome実装時に最低限確認する。

### Endpoint precedence

```text
--cdp-endpoint
> <SITE>_CDP_ENDPOINT
> CRAWLER_CDP_ENDPOINT
> default 9222
```

### Lifecycle

- CDP connectionから既存BrowserContextを取得できる
- Crawler用Pageを作れる
- crawl終了時にCrawler Pageだけcloseする
- remote Chrome process自体をcloseしない
- loginとcrawlが同じBrowser Session helperを利用できる

### Adapter boundary

- Adapterがendpoint/profile/Chrome launchを要求しない
- AdapterへPlaywright Pageを渡せば従来どおり動く

Discovery Adapterがreal browserを必要とする場合も、browser/session lifecycleをAdapter自身に持たせない。

Raw CDP helperを追加する場合は、Playwright APIで代替できない理由をtest/docに残す。

## 4. Integration Tests

`tests/integration/test_local_viewer_flows.py` でPlaywright + 人工ローカルviewerを使う。

主な対象:

- CONTENT → CONTENT → END
- AD skip
- NEXT_CONTENT
- LOADING → CONTENT
- unresolved LOADING timeout
- UNKNOWN stop
- same-content guard
- spread capture
- max_pages境界
- Manga ONEのimage-disappearance END heuristic
- Manga ONE chapter change

外部サイトへ常時依存するCIテストは置かない。

Integration testsはChromiumが利用できない環境ではskipされる。そのためpytest exit codeだけでなくpassed / skipped件数も確認する。

Discovery実装後は、人工listing fixtureを使ったintegration testを追加し、外部実サイトをCI authorityにしない。

## 5. Packaging tests

最低限:

- manifest記載PNGだけZIPへ入る
- manifest外の古いPNGはZIPへ入らない
- manifest記載PNG欠落は失敗
- 無関係ファイルがあるsource directoryをrmtreeしない

Batch統合後は、packaging成功時だけCatalog itemをcompletedへ更新し、archive pathを保存することも確認する。

## 6. 実サイト確認

Adapterの挙動を変更する場合は、可能な範囲で対象サイトを確認する。

最低観点:

1. 開始直後
2. 通常数ページ
3. spread / single transition
4. 広告前後（存在する場合）
5. 最終本文
6. 最終本文後
7. NEXT_CONTENT
8. 読み込みが遅いケース

Discovery Adapter追加時は、可能な範囲で以下も確認する。

- target作品だけを列挙する
- external ID / URL
- title / kind / order
- free / owned / quota / paid表示
- 期間限定無料表示と終了日時
- latest側の順序
- fullで最終itemまで到達すること
- incrementalで既知領域へ到達できること

実サイトの著作物・DOM snapshotを恒久fixtureへコピーしない。

## 7. Browser Session migration smoke test

共通 `.chrome-crawler/` でBookWalker/Manga ONEそれぞれのlogin/crawlとsession共存を確認済みである。以後はこの確認項目をBrowser Session回帰の基準として維持する。

### 共通Chrome

- 同じCrawler Chrome processへ接続できる
- BookWalker login sessionが維持される
- Manga ONE login sessionが維持される
- 一方のloginが他方を壊さない
- Crawler Pageを閉じてもChromeと他tabは残る

### BookWalker

- 商品ページ→viewer
- single/spread capture
- final END

### Manga ONE

- chapter viewer
- spread order
- final image disappearance END

Browser Session移行のためにsite-specific viewer logicを変更しない。

## 8. Regression priority

優先度が高い失敗:

- 最終本文を保存せず終了
- viewer終端を認識できずtimeout
- 広告やnext contentを本文として保存
- 同一ページを大量保存
- 古いrun PNGを新ZIPへ混入
- user fileをcleanupで削除
- UNKNOWNなのに進行
- Coreへのsite-specific分岐混入
- AdapterへのCDP/profile管理混入
- Crawler終了時にremote Chromeを誤ってclose
- site-specific overrideがglobal defaultを壊す
- Watchlist外の作品をDiscoveryする
- incomplete full syncで既存sourceをunavailableにする
- incrementalで未観測過去sourceをunavailableにする
- cross-site duplicateを自動mergeする
- Discoveryでcompleted/local_pathを上書きする
- paid/unknown sourceを自動crawlする
- quotaを誤って二重消費扱いする
- crawl失敗をcompleted扱いする

## 9. Discovery Sync Tests

### Full sync

最低限:

- empty Catalogへ全sourceを追加
- 同じfullを再実行してsourceを重複作成しない
- 既存sourceのURL変更を更新
- free -> paid / paid -> freeを更新
- `free_until`変更を更新
- `complete=true` で未観測sourceを `available=false` にする
- `complete=false` では未観測sourceを変更しない
- sourceを物理削除しない
- completed/local_pathを維持する
- `discovery_key` が異なるsourceへmissing判定を波及させない

### Incremental sync

最低限:

- latest側の未知sourceを追加
- 複数の新規sourceを追加
- known 1件では継続
- known 2件連続で停止
- unknownが途中に入ればknown streakをreset
- 走査中に見たknown sourceのexternal stateをrefresh
- 未観測過去sourceをunavailableにしない

### Cross-site duplicate

- 別siteで同title/kind/order候補をwarningできる
- warningだけで自動mergeしない
- warningだけで自動completed化しない
- heuristic不一致で既存itemを書き換えない

## 10. Batch / Site Policy Tests

最低限:

- 期限が近いfreeを通常freeより優先
- freeをownedより優先
- ownedをquotaより優先
- paid / unknownを除外
- quota上限到達時にskip
- quota scopeがsite単位/作品単位等のPolicyに従う
- quota消費をcrawl開始時に永続化
- `access_granted_until` 内のretryでPolicyに従い追加quotaを消費しない
- grant期限後は再度quota eligibilityを評価
- crawl成功 + packaging成功でcompleted/local_path更新
- crawl失敗でpendingを維持
- `item_id / source_id / archive path` の対応が維持される
- Batchが既存Crawlerへ `site + URL` を渡し、CrawlerRunnerへCatalog依存を追加しない
