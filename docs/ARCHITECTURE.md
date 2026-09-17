# Architecture

## 1. 設計原則

依存方向を単純に保つ。

現行Crawlerの目標architecture:

```text
Dedicated Crawler Chrome
    └─ shared profile (.chrome-crawler/)
            ↑
            │ CDP
            ↓
Browser Session Layer
    └─ Playwright Browser / BrowserContext / Page
            ↓
Core Runner / packaging
            ↓
Site Adapter
    └─ Playwright Page / Locator
```

Discovery / Batchを含む上位architecture:

```text
watchlist.yaml
      ↓
Discovery Service
      ↓
Discovery Adapter
      ↓
Catalog Service -> catalog.sqlite
      ↓
Batch Runner -> Site Policy
      ↓
Core Runner / packaging
      ↓
Site Adapter
```

重要な分離:

- **CDP**: Chrome sessionへ接続するためのtransport
- **Playwright**: navigation / DOM / click / wait / capture等の標準操作API
- **Site Adapter**: site固有viewer logic
- **Discovery Adapter**: site固有listing/discovery logic
- **Catalog Service**: SQLite read/write
- **Batch Runner**: Catalogからcrawl対象sourceを選ぶorchestration
- **Site Policy**: site固有quota/eligibility rule

Raw CDP Protocolを通常のsite操作APIにはしない。

CrawlerRunnerとDiscovery AdapterはCatalogを直接知らない。

## 2. ディレクトリ責務

### `core/`

サイト非依存ロジック。

- `models.py`: 共通データ構造
- `state.py`: PageState
- `browser.py`: Playwright lifecycle / CDP接続 / Browser Session補助
- `runner.py`: 状態ループ
- `capture.py`: capture / PNG保存
- `fingerprint.py`: SHA-256
- `progress.py`: manifest / progressと新規run安全確認
- `diagnostics.py`: 異常時情報
- `packaging.py`: manifest基準のZIP/library出力
- `errors.py`: 独自例外

### `site_adapters/`

サイト固有の**1 content viewer**差分。

- `base.py`: Adapter contract
- `registry.py`: site名→Adapter
- `<site>/adapter.py`: サイト固有実装
- `<site>/login.py`: 必要な場合のsite固有login DOM操作
- `<site>/README.md`: 実観測、終了挙動、制約、確認記録
- `<site>/config.yaml`: 実装が明示的に読み込む場合のみ設定として有効

現行real adaptersでは、複雑なselector/state/timeoutはPython Adapter実装がauthorityである。未使用YAMLとPythonを二重authorityにしない。

### `discovery/`（planned）

Watchlist targetからitem/source候補を列挙する。

想定責務:

- Discovery Service
- Discovery Adapter contract / registry
- site-specific discovery implementation
- full / incremental traversal orchestration
- duplicate candidate warningのためのCatalog query coordination

Discovery Adapter自身はSQLiteを直接read/writeしない。

### `catalog/`（planned）

SQLite Catalogを扱う。

- `items`
- `sources`
- upsert
- query
- completed/local artifact state update

詳細schemaは `docs/DISCOVERY_AND_BATCH.md` をauthorityとする。

### `batch/`（planned）

Catalogから対象sourceを選び、既存Crawlerを呼ぶ。

- eligible source selection
- source priority
- quota記録
- Site Policy呼び出し
- crawl success後のCatalog update

CrawlerRunnerへこの責務を移さない。

### `patterns/`

再利用可能な表示方式の補助部品。必須frameworkではない。

### `probe/`

新規サイト調査用。

## 3. Browser Session Layer

Browser Session Layerは、site固有logicの外側で以下を担当する。

- CDP endpoint解決
- 既存Crawler Chromeへ `connect_over_cdp()`
- BrowserContext取得
- Crawler用Page作成
- Crawlerが作成したPageだけclose
- remote Chrome processをCrawler終了時にcloseしない

Site Adapterはこのlayerを知らない。

Adapterへ渡る時点では単なるPlaywright `Page` であり、そのPageがlaunch済みbrowser由来かCDP由来かをAdapterは判断しない。

Discovery実装もreal-site browserを必要とする場合は同じBrowser Session Layerを再利用してよいが、browser lifecycleをDiscovery Adapterへ持ち込まない。

## 4. 共通Crawler Chrome / profile

Real-site automationの標準は1つのCrawler Chromeと共通profile。

目標:

```text
.chrome-crawler/
├─ bookwalker.jp のCookie / storage
├─ manga-one.com のCookie / storage
└─ その他siteのCookie / storage
```

これは論理的な説明であり、実際のChrome profile filesystem構造をCrawlerが直接管理するという意味ではない。

認証状態のauthorityはChrome profile。CrawlerはCookieやstorage stateをsite別JSONへ複製して標準管理しない。

profile directoryはrepositoryへcommitしない。

## 5. Endpoint resolution

目標のCDP endpoint優先順位:

```text
--cdp-endpoint
    ↓
<SITE>_CDP_ENDPOINT
    ↓
CRAWLER_CDP_ENDPOINT
    ↓
http://127.0.0.1:9222
```

通常は `CRAWLER_CDP_ENDPOINT` またはdefaultだけで全siteを扱う。

site-specific endpointは例外用:

- 別accountが必要
- extension / browser settingが違う
- sessionを分離したい
- 共通profileではsiteが正常動作しない

例外を標準設計へ昇格させない。

## 6. Playwrightを標準操作APIとする

CDPで接続した後も通常操作はPlaywrightで行う。

```python
page.goto(...)
page.locator(...)
locator.click()
page.wait_for_function(...)
locator.screenshot(...)
page.evaluate(...)
```

Raw CDP ProtocolはPlaywrightに適切なAPIがない場合のみBrowser Session/Coreの小さいhelperへ隔離する。

Site AdapterやDiscovery Adapterへ低レベルCDP session操作を広げない。

## 7. Authentication

login CLIはBrowser Session Layerから既存Crawler Chromeへlogin用Pageを新規作成し、site固有login functionがPlaywrightでDOM操作する。既存タブは再利用しない。

```text
Crawler Chrome/profile
    ↓ CDP
new login Page
    ↓
login_bookwalker / login_mangaone / future login handler
```

認証情報のinputは `.env` 等から取得してよいが、login後sessionの保存はChrome profileへ任せる。

Crawler独自のsite別auth-state fileは標準経路にしない。

CAPTCHA / MFA / validation errorは自動突破しない。

## 8. Runnerの概念フロー

```text
ensure output directory is new/empty
Browser SessionからPageを取得
prepare page
open URL
adapter.initialize
initial context
create manifest/progress

loop:
    state = adapter.detect_state

    END/NEXT_CONTENT:
        stop normally

    UNKNOWN:
        diagnostics + error

    AD:
        go_next + bounded wait

    CONTENT:
        enforce max_pages before additional capture
        validate context
        get identity
        get one or more capture targets
        capture
        SHA-256 fingerprint dedupe
        save PNG + manifest/progress
        go_next + bounded wait

normal terminal:
    crawler Pageをclose
    package output
    Crawler Chrome自体は残す
```

`max_pages`到達後も、次stateがEND/NEXT_CONTENTなら正常終了できる。

Batch Runnerはこのflowの外側にあり、Catalogから `site + URL` を選んで既存runを開始する。

## 9. Duplicateの考え方

現行Runnerはcapture fingerprintを保存重複判定authorityにする。ContentIdentityはAdapterのchange detection、manifest、debug情報として重要だが、保存dedupeをidentity優先へ変更しない。

この判断はBookWalker/Manga ONEの既知挙動維持を優先したもの。変更する場合はreal viewerの連続spread/遷移を先に観測する。

Discovery側のcross-site duplicateは別問題として扱う。別siteの類似itemはwarningを出しても、自動mergeしない。

## 10. Output / packaging

manifestのページ一覧を完成成果物のauthorityとする。packagingでdirectory globをauthorityにしない。

新規runは非空output directoryを拒否する。正常packaging後も、無関係ファイルが含まれるdirectoryは丸ごと削除しない。

Batch Runnerはpackaging成功後のarchive pathをCatalog itemへ記録できるが、packaging自体はCatalogを知らない。

## 11. Site Adapterの最小契約

概念上:

```python
prepare_page(page)
initialize(page)
detect_state(page)
get_capture_target(page)
get_capture_targets(page)
cleanup_capture_targets(page)
get_content_identity(page)
get_content_context(page)
go_next(page)
wait_for_change(page, previous_identity)
```

実際のdefault method / optional hookは `site_adapters/base.py` をauthorityとする。

Adapterは以下をしない。

```text
Chrome launch
profile選択
CDP endpoint解決
connect_over_cdp
BrowserContext lifecycle管理
Discovery listing traversal
Catalog read/write
```

## 12. Site固有の終了判定

終了方法は共通化しすぎない。

- BookWalkerはviewer DOM / page counter / known final transitionを使う
- Manga ONEはchapter URL changeと、最終advance後にpage imagesが一定時間消失する既知挙動を使う

「明示END DOMがなければENDにしない」のような一般ルールで、実サイト確認済み挙動を置換しない。

## 13. Safety

別コンテンツや無関係ファイルを誤処理するより停止を優先する。

- UNKNOWNは停止
- retryはbounded
- 非空run dirは拒否
- resumeは暗黙実行しない
- packagingはmanifestをauthorityにする
- Coreへsite-specific ifを追加しない
- Adapterへbrowser/session管理を入れない
- Watchlist外を無制限Discoveryしない
- incomplete full syncでmissing sourceをunavailableにしない
- incrementalで未観測過去sourceをunavailableにしない
- cross-site duplicateを自動mergeしない
- paid/unknown sourceを自動crawlしない

## 14. 移行状態

Browser Session architectureは採用済みで、共通launcherとshared-profile live verificationまで完了している。

標準launcherは `start_crawler_chrome.ps1`、profileは `.chrome-crawler`、global endpointは `CRAWLER_CDP_ENDPOINT` である。site別launcherは削除済みで、site-specific endpoint/profileは例外overrideとしてのみ扱う。BookWalker/Manga ONEのshared-profile login/crawlとsession共存はlive verification済みである。

BookWalker/Manga ONEのviewer/capture/END判定は変更せず、Browser Session Layerと運用launcherだけを共通化した。

Discovery / Catalog / Batch architectureは採用仕様として文書化済みだが、2026-09-17時点では未実装である。

## 15. Discovery / Catalog / Batch dependency rules

上位subsystemの依存方向は次を守る。

```text
Watchlist loader
      ↓
Discovery Service ─────→ Catalog Service
      ↓                        ↑
Discovery Adapter              │
                               │
Batch Runner ───────→ Site Policy
      │
      ↓
existing crawl orchestration
      ↓
CrawlerRunner -> Site Adapter
```

### Discovery Adapter

site固有の作品一覧・話一覧・access状態の観測だけを担当する。

- DB APIを呼ばない
- cross-site mergeしない
- Batch policyを知らない

### Discovery Service

- Watchlist targetを選ぶ
- `full / incremental` を実行する
- Adapter結果をCatalogへupsertする
- `full + complete` の場合だけscope内missing sourceをunavailable化する
- cross-site duplicate candidateをCatalogから照合しwarningする

### Catalog Service

- SQLiteの `items / sources` をauthorityとしてread/writeする
- Watchlist `key` を `discovery_key` としてsource scopeに保持する
- external discovery stateとlocal completed stateを混同しない

### Batch Runner

- pending item/sourceをCatalogから読む
- free/owned/quota等の優先順位を適用する
- Site Policyでquota eligibilityを判定する
- 必要なquota消費状態をcrawl開始時に永続化する
- 既存Crawlerへ `site + URL` を渡す
- packaging成功時だけcompleted/local_pathを更新する

### Site Policy

site固有のquotaや再閲覧猶予を扱う。

汎用rule DSLは作らず、必要なsiteだけ小さいPython Policyとして実装する。
