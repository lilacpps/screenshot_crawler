# Test Strategy

## 1. 目的

Core回帰、Browser Session回帰、Site Adapter前提崩壊を分けて検出する。実サイト確認済みの挙動を、根拠なく一般化したロジックで置換しない。

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

## 5. Packaging tests

最低限:

- manifest記載PNGだけZIPへ入る
- manifest外の古いPNGはZIPへ入らない
- manifest記載PNG欠落は失敗
- 無関係ファイルがあるsource directoryをrmtreeしない

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

実サイトの著作物・DOM snapshotを恒久fixtureへコピーしない。

## 7. Browser Session migration smoke test

共通 `.chrome-crawler/` 実装後にBookWalker/Manga ONEそれぞれで確認する。

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
