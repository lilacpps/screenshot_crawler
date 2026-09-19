# Architecture

## Phase 4A status

The Manga ONE Discovery adapter is implemented in
`site_adapters/mangaone/discovery.py` and registered separately from the
viewer `AdapterRegistry`. It reads `#chapterList` newest-first, uses the
chapter id from a card href or the observed `/chapter/<id>.webp` image URL,
and follows bounded `次へ` pagination. Uncertain traversal is incomplete;
only normal exhaustion allows full reconciliation. The adapter does not own
BrowserSession lifecycle or Catalog access. BookWalker Discovery, Batch
Runner, Site Policy, and quota consumption remain unimplemented for Phase 4A.

The Phase 5A read-only Batch Planner and Manga ONE Site Policy are now
implemented. They select Catalog sources and create plan candidates only;
Phase 5B adds sequential Manga ONE candidate execution, quota persistence,
packaging, and completed-item updates. BookWalker Batch execution remains
unsupported.

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
Crawl Request
  site / URL / access_strategy / optional metadata
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
- **Site Policy**: site固有quota/eligibility ruleを解決する
- **Crawl Request**: Batch/CLIから既存Crawlerへ渡すsite-neutralな実行入力

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

Crawl Requestは既存`RunConfig`を最小限拡張して保持する。Catalog objectをCoreへ流さず、site-neutralなrun inputだけを渡す。

### `site_adapters/`

サイト固有の**1 content viewer**差分。

- `base.py`: Adapter contract
- `registry.py`: site名→Adapter
- `<site>/adapter.py`: サイト固有実装
- `<site>/login.py`: 必要な場合のsite固有login DOM操作
- `<site>/README.md`: 実観測、終了挙動、制約、確認記録
- `<site>/config.yaml`: 実装が明示的に読み込む場合のみ設定として有効

現行real adaptersでは、複雑なselector/state/timeoutはPython Adapter実装がauthorityである。未使用YAMLとPythonを二重authorityにしない。

Site Adapterは、必要なsiteではCrawl Requestの `access_strategy` を参照し、quota用入口かdirect入口か等のsite固有操作を選択できる。quota上限やreset rule自体は知らない。

### `discovery/`（framework実装済み、site adapterはplanned）

Watchlist targetからitem/source候補を列挙する。

実装済みの責務:

- Discovery Service
- Discovery Adapter contract / registry
- site-specific discovery Adapterを受け入れるcontract
- full / incremental traversal orchestration
- default known-streak incremental stop
- site固有のstable boundaryが必要な場合に小さいincremental stop policyを受け入れる拡張点（BookWalkerが利用）
- duplicate candidate warningのためのCatalog query coordination

Discovery Adapter自身はSQLiteを直接read/writeしない。

共通framework、Manga ONEのreal-site listing Adapter、BookWalkerのseries-scoped real-site
listing Adapterを実装している。BookWalkerはWatchlistへ手動登録した `/series/<id>/list/` を
scope authorityとしてDiscoveryする。

### `catalog/`（Watchlist + Catalog基盤実装済み）

SQLite Catalogを扱う。

- `items`
- `sources`
- upsert
- query
- completed/local artifact state update

初期schemaとservice/repository、Discovery Serviceから利用するscope query/reconciliation APIは実装済みである。Phase 5Aのread-only Batch Planner / Site Policy orchestration、Phase 5BのManga ONE Batch Executor（Crawler実行、quota local state、packaging、completed更新）、BookWalkerのseries-scoped Discovery / Policy / strict direct・quota entryも実装済みである。

Catalog itemは、取得可能な範囲でtitle/author/genre/order等のpackaging metadataも保持できる。

詳細schemaは `docs/DISCOVERY_AND_BATCH.md` をauthorityとする。

### `batch/`（implemented）

Catalogから対象sourceを選び、既存Crawlerを呼ぶ。

- eligible source selection
- source priority
- quota記録
- Site Policy呼び出し
- `access_strategy` 解決
- Crawl Request作成
- known metadataのoptional override入力
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
receive site-neutral Crawl Request
ensure output directory is new/empty
Browser SessionからPageを取得
prepare page
adapter receives run access intent
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
        optional adapter direct capture
        if unavailable, get one or more capture targets
        capture
        SHA-256 fingerprint dedupe
        save PNG + manifest/progress
        go_next + bounded wait

normal terminal:
    crawler Pageをclose
    resolve packaging metadata
    package output
    Crawler Chrome自体は残す
```

`max_pages`到達後も、次stateがEND/NEXT_CONTENTなら正常終了できる。

Batch Runnerはこのflowの外側にあり、CatalogとSite PolicyからCrawl Requestを作る。

## 9. Access strategy boundary

`source.access_mode` と `Crawl Request.access_strategy` は別概念とする。

```text
Catalog source state:
  owned / free / quota / paid / unknown

Crawl execution intent:
  auto / direct / quota
```

Batch Runner / Site Policyがsource stateとgrant状態を評価し、今回のaccess strategyを決める。

例:

```text
quota source + active grant -> direct
quota source + no active grant + eligible -> quota
manual crawl -> auto
```

Coreはdaily limit、reset時刻、quota scope等を解釈しない。

Site Adapterが必要なsite固有button/entry操作だけを担当する。

Manga ONEのquota entryはCSR mount後に現れるため、Adapter内で最大2秒、100ms間隔のbounded waitを行う。候補数1件かつvisibleのbuttonだけをクリックし、曖昧な状態ではfirst要素を選択しない。

## 10. Duplicateの考え方

現行Runnerはcapture fingerprintを保存重複判定authorityにする。ContentIdentityはAdapterのchange detection、manifest、debug情報として重要だが、保存dedupeをidentity優先へ変更しない。

この判断はBookWalker/Manga ONEの既知挙動維持を優先したもの。変更する場合はreal viewerの連続spread/遷移を先に観測する。

Discovery側のcross-site duplicateは別問題として扱う。別siteの類似itemはwarningを出しても、自動mergeしない。

## 11. Output / packaging

Page artifacts are format metadata driven. Locator/canvas capture keeps the
default PNG behavior; Adapter direct capture may return original source bytes
with MIME type and extension. Runner and manifest persistence follow that
metadata, while packaging validates and includes only manifest-declared safe
PNG/WebP artifacts. This remains site-neutral; source-byte selection belongs
inside the Site Adapter.

manifestのページ一覧を完成成果物のauthorityとする。packagingでdirectory globをauthorityにしない。

新規runは非空output directoryを拒否する。正常packaging後も、無関係ファイルが含まれるdirectoryは丸ごと削除しない。

Batch Runnerはpackaging成功後のarchive pathをCatalog itemへ記録できるが、packaging自体はCatalogを知らない。

### 11.1 Output metadata resolution

packaging用metadataはfieldごとに:

```text
1. Crawl Request explicit metadata
2. Site Adapter metadata
3. packaging fallback
```

の順で解決する。

Crawl Requestでtitleだけ指定し、author/order/genreはAdapterへfallbackするような部分指定を許可する。

metadata overrideはmanifest/source URLのauthorityにはならない。

## 12. Site Adapterの最小契約

現行contractの概念:

```python
prepare_page(page)
configure_run(page, access_strategy)
initialize(page)
detect_state(page)
get_capture_target(page)
get_capture_targets(page)
cleanup_capture_targets(page)
capture_page(page) -> tuple[CaptureResult, ...] | None
get_content_identity(page)
get_content_context(page)
go_next(page)
wait_for_change(page, previous_identity)
```

実際のdefault method / optional hookは `site_adapters/base.py` をauthorityとする。

`capture_page()`は任意の直接capture hookである。非`None`の非空tupleを返した場合、Coreは
Locator captureを行わない。`None`、`CaptureUnavailableError`、bounded timeoutでは既存の
target captureへfallbackする。temporary resourceのcleanupは直接capture hook側が担当する。
このhookのsite-specificな実装はAdapter内に置き、CoreはBookWalker等のsite名を判定しない。

Crawl Requestの実装では、既存`RunConfig`へsite-neutralなrun access intentとoptional output metadataを最小限保持し、Adapterへ`configure_run(page, access_strategy)`で渡す。既定hookは`auto`だけを受け付け、未対応の`direct`/`quota`は明示的に停止する。Manga ONE Adapterは`auto`/`direct`/`quota`を受け付け、site-specific entry操作を実行する。

Adapterは以下をしない。

```text
Chrome launch
profile選択
CDP endpoint解決
connect_over_cdp
BrowserContext lifecycle管理
Discovery listing traversal
Catalog read/write
Site Policyによるquota eligibility判定
```

## 13. Site固有の終了判定

終了方法は共通化しすぎない。

- BookWalkerはviewer DOM / page counter / known final transitionを使う
- Manga ONEはchapter URL changeと、最終advance後にviewport内へ表示される終端UI marker、またはpage imagesが一定時間消失する既知挙動を使う。終端markerの連続表示確認中は、一時的なpage imageのidentity変化より終端判定を優先する。DOM上に存在するだけのviewport外markerは終端扱いしない

「明示END DOMがなければENDにしない」のような一般ルールで、実サイト確認済み挙動を置換しない。

## 14. Safety

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
- default known-streakがsite固有access遷移に安全でない場合は、site-specific stable boundary policyを許容する
- cross-site duplicateを自動mergeしない
- paid/unknown sourceを自動crawlしない
- active quota grantを新規quotaとして二重消費扱いしない
- Site Policy ruleをCrawlerへ持ち込まない
- BookWalker Discoveryでreaderを開いてまる読みtimerを開始しない
- BookWalker `quota` strategyからtrial/owned/subscriptionへfallbackしない
- BookWalker `direct` strategyからtrial/maruyomi/subscriptionへfallbackしない
- `batch plan` はCatalogのstatus/local/quota stateを変更しない

## 15. 移行状態

Browser Session architectureは採用済みで、共通launcherとshared-profile live verificationまで完了している。

標準launcherは `start_crawler_chrome.ps1`、profileは `.chrome-crawler`、global endpointは `CRAWLER_CDP_ENDPOINT` である。site別launcherは削除済みで、site-specific endpoint/profileは例外overrideとしてのみ扱う。BookWalker/Manga ONEのshared-profile login/crawlとsession共存はlive verification済みである。

BookWalker/Manga ONEのviewer/navigation/END判定は維持する。BookWalkerだけはAdapter内で
source-native captureを先に試し、必要時に既存Canvas cropへfallbackする。Browser Session Layerと
運用launcherはsite-neutralなままとする。

Watchlist loader、Catalog Service（`items` / `sources`）、Crawl Requestの最小基盤、site-neutral Discovery framework、
Phase 5AのBatch Planner / Site Policy基盤、Manga ONE Policy、Phase 5BのManga ONE Batch Executor、
BookWalkerのseries-scoped Discovery / Policy / Batch integration / strict direct・quota entry、
およびsource-native captureを実装済みとする。

## 16. Discovery / Catalog / Batch dependency rules

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
Crawl Request
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
- known output metadataをNULL許容で保持できる

### Batch Runner

- Phase 5Aではpending item/sourceをread-onlyでCatalogから読む
- free/owned/quota等の優先順位を適用する
- Site Policyでquota eligibilityを判定する
- active grantを評価し、`direct / quota` を解決する
- Catalog metadataをoptional overrideとしてplan candidateへ入れる
- quota仮予約はmemory内だけで行い、Catalogへ永続化しない
- `quota_available` は計画前のlocal枠、`quota_remaining` は仮予約後の残枠を表す
- Phase 5Bではcandidateを順番に実行し、quota candidateはCrawler開始直前にlocal stateを保存する
- crawlとpackagingが成功した後だけ`items.status` / `local_path` / `completed_at`を更新する
- crawl、viewer、packagingの失敗時はitemをcompletedにせず、quota stateは保持する
- candidateごとに一意なrun directoryを使い、stop-on-first-failureで後続を実行しない

### Site Policy

site固有のquotaや再閲覧猶予を扱う。

汎用rule DSLは作らず、必要なsiteだけ小さいPython Policyとして実装する。

Phase 5Aでは `SitePolicyRegistry` にManga ONEだけを登録する。未登録siteは
明示エラーとして停止する。Manga ONE Policyはsite-wideのlocal quotaを4枠とし、
09:00/21:00 JSTのhalf-open windowで`quota_started_at`を数える。active grant
（`access_granted_until > now`）はdirect扱いでslotを消費しない。利用者の手動消費や
外部clientの残量はCatalogから観測できないため、これはlocal eligibility estimateである。

### Crawl Request

Batchまたは手動CLIからCrawlerへ渡すsite-neutralな実行入力。

- `site`
- `url`
- `access_strategy = auto | direct | quota`
- optional `title / author / order / genre`

Catalog identityやquota ruleそのものは含めない。
