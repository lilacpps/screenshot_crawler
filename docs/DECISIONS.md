# Design Decisions

## D-001 Pythonを採用

### 決定
Python 3.12+ + Playwright Pythonを使用する。

### 理由
必要なPlaywright機能を満たし、利用者の習熟度を優先する。

---

## D-002 万能自動判定をv1で目指さない

### 決定
新規サイトはprobeしてSite Adapterを追加する。

### 理由
終了挙動・広告・次コンテンツ遷移がサイトごとに異なり、完全自動化は誤取得リスクが高い。

---

## D-003 CoreとSite Adapterを分離

### 決定
サイト固有ルールをCoreに入れない。

### 理由
サイト追加・修正ごとの回帰を抑える。

---

## D-004 設定ファイルだけで全挙動を表現しない

### 決定
設定ファイルは必要な単純データに限定し、複雑なロジックはPython Adapterに置く。未使用configをauthority扱いしない。

### 理由
独自DSL化と二重authorityを避ける。

---

## D-005 UNKNOWNでは停止

### 決定
不明状態で自動継続しない。

### 理由
別コンテンツ・広告・意図しない画面を大量保存するリスクを抑える。

---

## D-006 Locator / content bufferを優先

### 決定
固定screen cropより本文Locatorを優先する。Canvasでraw PNGを取得できる場合はcontent bufferを利用する。

### 理由
viewer UI混入と画面環境依存を減らす。

---

## D-007 Patternは補助部品

### 決定
Patternを重い継承frameworkにしない。

### 理由
例外が多い領域で抽象化を先行させない。

---

## D-008 Real-site automationはCDP接続を標準とする

### 決定
Real-siteの `crawl` / `login` は、外部で起動した通常ChromeへPlaywright `connect_over_cdp()` で接続する方式を標準とする。

Crawlerが実サイトごとにChromiumをlaunchして認証状態を個別管理する方式は標準にしない。

### 理由
通常Chromeのlogin/session、Cookie、localStorage等を維持しやすく、viewer固有の通常browser挙動を保ちやすい。またCrawler終了時にChrome process自体を終了せず、Crawlerが利用したPageだけを閉じられる。

---

## D-009 Resumeはv1.1では未実装

### 決定
既存の非空run directoryは拒否し、暗黙resumeやmanifest/progress上書きを行わない。

### 理由
不完全なresumeより既存成果物保護を優先する。

---

## D-010 保存dedupeはcapture fingerprintをauthorityとする

### 決定
現行RunnerではSHA-256 capture fingerprintを保存重複判定に使う。ContentIdentityはchange detectionと記録に利用する。

### 理由
実サイトで動作していたBookWalker/Manga ONEの遷移挙動を維持する。identity優先へ変更する場合は実viewerの連続spread等を先に確認する。

---

## D-011 Manifestをpackaging authorityとする

### 決定
ZIP対象はdirectory globではなくmanifest `pages[].file` とする。新規runは非空directoryを拒否し、無関係ファイルを含むsource directoryは丸ごとcleanupしない。

### 理由
古いPNG混入とuser file削除を防ぐ。

---

## D-012 Site固有の終端ヒューリスティックを許容する

### 決定
END判定に全サイト共通の「明示END DOM必須」ルールを置かない。実観測が安定している場合はboundedなsite-specific heuristicをAdapterに置く。

### 理由
Manga ONEでは最終advance後のpage image消失が実動作上の終端signalであり、未確認generic selectorへの置換の方が回帰リスクが高い。

---

## D-013 `note/` を現行実装スナップショットとして同期する

### 決定
仕様・実装・テスト・運用方法を変更した場合、同じ変更の中で対応する `note/` を更新する。

- Core共通変更は `note/00_core.md`
- Site固有変更は対応するsite note
- 共通変更がsite挙動へ影響する場合は両方

noteは履歴ログではなく「現在どう動くか」を詳しく説明する場所とする。履歴はGitと `docs/DECISIONS.md` に残す。

noteはauthority orderではcode/testsより下に置き、上位authorityと競合した場合はnoteを修正する。

### 理由
実装詳細をチャットや過去コミットだけに依存せず、次回作業時に現在の前提・既知の実サイト挙動・運用方法を素早く復元できるようにするため。

---

## D-014 共通Crawler Chrome / profileを標準とする

### 決定
Real-site automationでは、原則として1つの専用Crawler Chromeと1つの共通profileを利用する。

目標profile:

```text
.chrome-crawler/
```

BookWalker、Manga ONE、将来追加するサイトの認証状態は、Chrome自身がこのprofile内のCookie / localStorage / IndexedDB等としてサイトごとに保持する。

Crawler側では `bookwalker-auth.json` のようなsite別storage-state fileを標準の認証authorityにしない。

### 理由
普通のChromeで複数サイトへログインするのと同じモデルに寄せることで、認証状態管理をCrawlerから切り離し、site追加時のbrowser/session実装を減らすため。

---

## D-015 接続はCDP、操作はPlaywrightを標準とする

### 決定
CDPはBrowser Sessionへの接続手段として使い、通常のサイト操作はPlaywrightの高水準APIで行う。

標準:

- `connect_over_cdp()`
- `Page`
- `Locator`
- `goto()`
- `click()`
- `wait_for_*()`
- `evaluate()`
- `screenshot()` / canvas capture

Raw CDP Protocol (`new_cdp_session()` / `session.send()` 等) は、Playwright APIでは実現困難なChrome固有機能が必要な場合だけ使う。

### 理由
Locator、auto-wait、frame/popup処理、timeout、screenshot等をPlaywrightへ任せた方が実装が単純で安定する。CDPを低レベル操作APIとして各Adapterへ広げると保守性が下がる。

---

## D-016 Site AdapterはBrowser接続方式を知らない

### 決定
Site AdapterはPlaywright `Page` / `Locator` を受け取り、サイト固有DOMとviewer挙動だけを扱う。

Adapterから以下を行わない。

- Chrome process launch
- profile directory選択
- CDP endpoint解決
- `connect_over_cdp()`
- BrowserContext lifecycle管理

これらはCLI / Browser Session Layerの責務とする。

### 理由
Browser session管理とsite-specific automationを分離し、新規site追加をAdapter実装だけに近づけるため。

---

## D-017 共通CDP endpointをdefaultとしsite-specific overrideを許可する

### 決定
目標のendpoint解決順は次とする。

1. 明示CLI `--cdp-endpoint`
2. site-specific `<SITE>_CDP_ENDPOINT`
3. global `CRAWLER_CDP_ENDPOINT`
4. default `http://127.0.0.1:9222`

通常はglobal endpointと共通Crawler Chromeを使う。siteごとに別profile / Chrome instanceが必要になった場合だけsite-specific endpointでoverrideする。

### 理由
通常運用を単純化しつつ、複数account、extension差、site固有設定、session分離などの例外を将来許容するため。

---

## D-018 Browser Session共通化は仕様先行で移行する

### 決定
まずdocsを上記モデルへ更新し、その後に実装を移行する。

移行期間中はsite-specific launcher/profileを一時的なrollback経路として扱っていたが、これは完了後の標準構成ではない。

### 理由
BookWalker/Manga ONEの実サイトで動作しているAdapter挙動を壊さず、browser/session層だけを段階的に差し替えるため。

---

## D-019 共通Crawler Chrome launcherを標準運用にする

### 決定
Phase 2以降のreal-site運用では、`scripts/start_crawler_chrome.ps1` がrepository root基準で `.chrome-crawler/` をprofileに使い、port `9222` でChromeを起動する。既存listenerがある場合はprocess command lineでportとshared profileを確認し、一致する場合だけ二重起動せず既存Chromeを利用する。確認できない場合はerrorで停止する。

BookWalker/Manga ONEのloginは共通Chromeの専用new Pageで実行し、login後はPageだけ閉じる。認証sessionはshared profileへ保存し、remote Chrome processは閉じない。

shared-profileでのBookWalker/Manga ONE login・crawl・session共存と既存viewer behaviorを確認できたため、site-specific launcherは削除し、共通launcherを唯一の標準real-site入口とする。

### 理由
siteごとのprofile競合を避け、BookWalkerとManga ONEのsessionを同じChromeで保持できるようにする。既存viewer behaviorを変更せず、運用入口だけを共通化するため。

---

## D-020 Discovery対象は明示Watchlistに限定する

### 決定
Discoveryは `watchlist.yaml` に利用者が明示登録したtargetだけを探索する。

各targetはstableな一意 `key`、`site`、Discovery起点 `url`、`enabled` を持つ。Watchlistからtargetをremove/disableしてもCatalogを自動削除しない。

### 理由
site全体の無制限探索を避け、個人利用で管理可能な対象範囲に限定するため。またstable keyをsourceのDiscovery scopeに残すことで、full sync時のmissing判定を安全に限定できる。

---

## D-021 WatchlistはYAML、CatalogはSQLite 2テーブルとする

### 決定
人間が管理するDiscovery targetは `watchlist.yaml` に保存する。

program-managed stateはSQLite `catalog.sqlite` の:

```text
items
sources
```

2テーブルを基本とする。

`works`、`crawl_jobs`、汎用history table等は初期実装では追加しない。

### 理由
設定と状態を分離しつつ、個人利用に対して過剰な正規化やDB構造を避けるため。

---

## D-022 Discovery AdapterはCatalogを知らない

### 決定
Discovery Adapterはsite固有のlisting/navigation/access-state観測を担当し、SQLiteへ直接read/writeしない。

Discovery ServiceがAdapter結果を受け取り、Catalog Serviceへupsertする。

### 理由
site固有Web操作と永続化を分離し、Adapter追加時にDB実装を持ち込まないため。既存Site AdapterとBrowser Sessionの責務分離と同じ原則を維持する。

---

## D-023 Discoveryはfull / incremental syncを持つ

### 決定
Discovery modeを次の2種類とする。

- `full`: target内の現在列挙可能な全sourceを同期する
- `incremental`: latest側から走査し、known sourceが2件連続したら停止する

full結果は `complete` を持ち、`complete=true` のときだけ同じ `discovery_key` scope内で今回未観測のsourceを `available=false` にできる。

incrementalでは未観測の過去sourceをunavailableにしない。

### 理由
初回/定期reconciliationでは過去access状態の変化も反映しつつ、通常更新では全件走査コストを避けるため。途中失敗したfull syncで既存sourceを誤って消失扱いすることも防ぐ。

---

## D-024 Discoveryはexternal stateだけを同期する

### 決定
DiscoveryはURL、access mode、free期限、availability、last seen等のsite側stateを同期する。

`completed`、`local_path`、`completed_at` 等のlocal artifact stateをDiscoveryで変更しない。

### 理由
site表示の変化によって、既に取得済みのlocal成果物状態が壊れることを防ぐため。

---

## D-025 別siteの同一作品は自動mergeしない

### 決定
異なるsiteのitem/sourceをtitleやISBN等で自動mergeしない。

Discovery時にnormalized title、kind、order等から別siteの重複候補を検出できる場合はwarningを出すが、warning onlyとする。

### 理由
site横断identity resolutionは誤mergeの影響が大きく、個人利用では自動統合より利用者への気付きの提供だけで十分だからである。

---

## D-026 Access stateとSite Policyを分離する

### 決定
sourceの現在状態は:

```text
owned / free / quota / paid / unknown
```

で表す。期間限定無料は `free + free_until` とする。

1日N回、作品単位quota、再閲覧猶予等のruleはBatch側のsite-specific Policyへ置き、汎用rule DSLを作らない。

quotaは基本的にcrawl開始時に消費記録し、site上で追加quotaなしに再閲覧可能な猶予がある場合は `access_granted_until` を保存して扱えるようにする。

### 理由
「そのsourceの現状」と「site全体/作品単位の利用rule」は別概念であり、同じDB fieldや複雑なconfigへ押し込むと保守性が下がるため。

---

## D-027 Batch RunnerはCatalogを知り、CrawlerRunnerは知らない

### 決定
Batch RunnerがCatalogからsourceを選択し、既存Crawlerへ `site + URL` を渡す。

CrawlerRunnerの1 URL -> 1 run責務を維持し、Catalog read/writeを持たせない。

基本source優先順位は:

```text
期限が近いfree
通常free
owned
quota
paid / unknownは対象外
```

crawl + packaging成功時だけitemをcompletedへ更新し、`item_id / source_id / archive path` を対応付ける。

### 理由
既存Crawlerの単純で検証済みの責務を壊さず、Discovery/Batchを上位orchestrationとして追加するため。
