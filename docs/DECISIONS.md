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

Schema v3では各targetはstableな一意 `key`、stableな `work_key`、`site`、Discovery起点 `url`、`enabled`、必須 `label` を持つ。`key` はDiscovery scope、`work_key` はWork identityを表す。Watchlistからtargetをremove/disableしてもCatalogを自動削除しない。

### 理由
site全体の無制限探索を避け、個人利用で管理可能な対象範囲に限定するため。またstable keyをsourceのDiscovery scopeに残すことで、full sync時のmissing判定を安全に限定できる。

---

## D-021 WatchlistはYAML、CatalogはSQLite 2テーブルとする（D-032でsuperseded）

### 決定
人間が管理するDiscovery targetは `watchlist.yaml` に保存する。

program-managed stateはSQLite `catalog.sqlite` の:

```text
items
sources
```

2テーブルを基本とする。

`works`、`crawl_jobs`、汎用history table等は初期実装では追加しない。

このCatalog構造に関する決定はD-032でsupersedeされる。Watchlistをhuman-managed YAMLとして分離する方針は維持する。

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
- `incremental`: latest側から走査し、defaultではknown sourceが2件連続したら停止する

site固有のaccess状態遷移によりknown-source streakが安全な境界にならない場合は、
Discovery frameworkに小さいsite-specific incremental stop policyを許容する。
default ruleは維持し、例外をCoreのsite名分岐にはしない。

full結果は `complete` を持ち、`complete=true` のときだけ同じ `discovery_key` scope内で今回未観測のsourceを `available=false` にできる。

incrementalでは未観測の過去sourceをunavailableにしない。

### 理由
初回/定期reconciliationでは過去access状態の変化も反映しつつ、通常更新では全件走査コストを避けるため。途中失敗したfull syncで既存sourceを誤って消失扱いすることも防ぐ。また、siteによって「既知であること」と「今後変化しない安定領域」が一致しないため、停止境界だけはsite固有policyで安全側へ調整できるようにする。

---

## D-024 Discoveryはexternal stateだけを同期する

### 決定
DiscoveryはURL、access mode、free期限、availability、last seen等のsite側stateを同期する。

`items.status`、`artifacts`、`completed_at` 等のlocal artifact stateをDiscoveryで変更しない。

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
Batch RunnerがCatalogからsourceを選択し、既存Crawlerへ実行入力を渡す。

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

---

## D-028 Source access stateとCrawler access strategyを分離する

### 決定
Catalogの `source.access_mode` と、今回のcrawlでCrawlerへ渡す `access_strategy` を別概念にする。

Catalog source state:

```text
owned / free / quota / paid / unknown
```

Crawler execution intent:

```text
auto
  手動crawlのdefault。Adapterがsite状態を観測して入口を選ぶ。

direct
  新規quotaを消費しない前提でreaderへ入る。

quota
  今回はquotaを利用してaccessを開始する。
```

Batch Runner / Site Policyがquota残数、scope、`access_granted_until` 等を評価して `direct` または `quota` を解決する。

例えばquota sourceでもgrant期間内なら `direct` とし、新規quota消費が必要な場合だけ `quota` とする。

Crawlerへdaily limit、reset rule、quota scope等のPolicy自体は渡さない。Site Adapterは受け取ったsite-neutralな実行意図をsite固有button/entry操作へ反映する。

### 理由
「sourceがquota対象である」ことと「今回新たにquotaを消費する」ことは同じではない。再閲覧猶予中のretry等を二重消費扱いせず、同時にCoreへsite固有quota ruleを持ち込まないため。

---

## D-029 Output metadataは明示入力を優先し不足分をAdapterで補完する

### 決定
Crawlerはpackaging用の `title / author / order / genre` をoptional inputとして受け取れるようにする。

metadata解決はfield単位で:

```text
1. Crawl Requestの明示non-empty値
2. Site Adapterが取得した値
3. packaging側の既存fallback
```

の順とする。

Catalog/Discoveryですでに分かっているmetadataはBatchがCrawlerへ渡してよい。一部fieldだけ指定し、残りをAdapterから取得することを許可する。

手動crawlではmetadata未指定をdefaultとし、現在のsite自動取得を維持する。

metadata overrideはsource URLやmanifestの実URLを置換しない。

### 理由
Batch経由ではDiscovery済みの確定情報を再利用でき、手動crawlでは従来の簡単なURL-only操作を維持できる。CrawlerへCatalog依存を追加せず、サイトDOMのtitle/author取得失敗にも強くするため。


---

## D-030 BookWalker Discoveryは手動登録series listをscope authorityとする

### 決定
BookWalker Discoveryは初期実装で、Watchlistへ明示登録された:

```text
https://bookwalker.jp/series/<series-id>/list/
```

だけを探索する。BookWalker全体や「まる読み10分」全対象の自動探索は行わない。

同じseries listに列挙された商品は、商品titleの文字列推定ではなく同一Discovery
group / packaging seriesとして扱う。stable source identityは商品UUID
`/de<uuid>/` とし、series scopeはWatchlist `discovery_key` で保持する。

Discoveryは各商品詳細ページのaccess controlを観測するがreaderは開かない。
access modeは強いsignalから `owned / quota / paid / unknown` を分類し、
`subscription_reading` actionだけを「まる読み10分」と解釈しない。

BookWalkerのincrementalは、既存 `paid / unknown` を再確認し、
run開始前から `quota / owned` だったsourceをstable boundaryとして停止する。
generic known-source 2件停止はBookWalkerには使わない。

BookWalker公式では、その日の「まる読み10分」終了後に対象作品でも通常の
「試し読み」が表示されるため、既知 `quota / owned` をtrial/unknown観測だけで
downgradeしない。

同じBookWalker external IDが別のnon-null discovery scopeに既存の場合、
scopeを黙って移動せずincompleteとして停止する。

### 理由
全作品探索は対象量が大きく個人利用の目的に合わない。series listを利用者が
明示選択することでscopeを小さく保てる。また同一series listはBookWalker自身の
groupingなので、title parsingよりseries identityとして信頼できる。

さらに「まる読み10分」終了後のtrial表示をそのままexternal state downgradeとして
保存すると、実際にはquota対象の既存作品を誤ってpaidへ戻すため、安全側に
stable-state preservationを採用する。

---

## D-031 BookWalker quota Batchは1日1冊・strict entryを採用する

### 決定
BookWalker公式の「まる読み10分」は1日合計10分、AM5:00 JST resetだが、
初期Batchでは残り秒数を最適化せず、Crawler側のlocal safety policyを:

```text
05:00 JST ～ 翌05:00 JST
BookWalker site-wide
quota start = 最大1冊
```

とする。

quota attemptはreaderを開く前に `quota_started_at` を記録し、crawl / packagingが
失敗しても同window内ではrefundや自動再試行をしない。

BookWalkerではManga ONEのようなsource単位の再閲覧grantを仮定せず、
`access_granted_until` をdirect判定へ使わない。

BookWalker Site AdapterのBatch entryはstrictにする。

- `quota`: 「まる読み10分」の強い固有controlだけをclickし、trial / owned /
  読み放題等へfallbackしない
- `direct`: 初期実装では購入済みfull reader「読む」だけをclickし、trial /
  maruyomi / 読み放題等へfallbackしない
- `auto`: 既存manual crawl互換のcandidate scoring/fallbackを維持する

requested strategyに合うcontrolが安全に一意決定できなければclick前に失敗する。

### 理由
Resume未実装の状態で10分を複数冊へ最大利用すると、途中でquotaが切れた巻を
安全に継続する仕組みが必要になり実装範囲が大きくなる。1日1冊なら既存の
1 URL -> 1 runモデルを維持できる。

また、trial readerは途中までしか読めなくても正常ENDし得るため、quota requestが
trialへfallbackするとpartial contentをcompleted扱いする危険がある。Batchでは
効率より誤completed防止を優先する。

---

## D-032 Catalog Schema v3は6テーブルを基本とする

### 決定
Schema v3のCatalogは次を基本構造とする。

```text
works
  └─ items
       └─ sources
            └─ source_targets

items
  ├─ crawl_runs
  └─ artifacts
```

画像・ZIP等のbinary本体はDBへ格納しない。SQLiteはidentity、external/local state、crawl履歴、
artifact metadataの正本とする。

### 理由
GUI、複数site、将来Android backend、実行履歴、成果物の移動・削除を、ItemやSourceの意味を
混ぜずに扱うため。DB容量はmetadata中心で小さく、binaryを分離することでbackupとstorage運用も分けられる。

---

## D-033 Workは管理上の刊行・配信系列とし、variantを先回りして正規化しない

### 決定
Workはユーザーが1作品として管理したい刊行・配信系列とする。Watchlistはstable `work_key` でWorkを参照し、
`label` は必須の人間向け表示名兼、新規Workの初期titleとする。

通常版、カラー版、合本版等はv3では別Workで扱ってよい。厳密な関連が必要になった時点で
`work_relations` / `item_relations` を追加する。

同じWorkで話ごとにsiteが違ってよい。同一Itemへのcross-site Source統合は自動で行わない。

### 理由
将来ケースを予測してEdition/Bundle等の階層を固定すると、未確認のsite要件にDBが引っ張られるため。
Work→Item→Sourceの境界を保てば、variant relationは追加tableで後から表現できる。

---

## D-034 CrawlRunとArtifactを分離し、DBを履歴の正本とする

### 決定
1回の取得試行は `crawl_runs` に成功・失敗とも記録する。実行時のItem/Source/Target参照に加え、
site/external_id/backend/target_key/locator等をsnapshotとして残す。

ZIP等の物理成果物は `artifacts` に分離し、SHA-256、byte size、storage backend、locator、
`present / missing / deleted / unknown` stateを保持する。Artifactは手動importを許容するため
`crawl_run_id=NULL` を許す。

Itemの `completed` は過去に正常取得済みという運用状態であり、Artifactの移動・missing・削除では
自動的にpendingへ戻さない。

### 理由
成果物は容量都合で移動・削除され得るが、「いつ何を取得し成功/失敗したか」は失いたくないため。
pathをidentityにせず、DBとpayload lifecycleを分離する。

---

## D-035 SourceTargetはbackendとtarget_keyで複数経路を表す

### 決定
SourceTarget identityは:

```text
UNIQUE(source_id, backend, target_key)
```

とする。通常Web Discoveryは `backend=web,target_key=default` をupsertする。
`backend` と `target_key` はCatalogではopaque stringとして扱い、enum固定しない。

同一SourceへWeb/Android等の複数targetを持てる。WebとAndroidでsite identityを共通化できない場合は、
同一Item配下の別Sourceとして保持してよい。

現行ExecutorはWebだけを実行し、Android対応時は上位dispatcherからWeb Runner / Android Runnerへ分岐する。
CrawlerRunnerやPlaywright PageをAndroid向け共通抽象へ無理に一般化しない。

### 理由
取得経路とcontent identityを分離し、将来backendや同backend内の複数routeが増えてもSource/Item schemaを
壊さないため。

---

## D-036 Schema v3は新規再構築し、v3以降はmigration + backupを標準とする

### 決定
v2→v3はmigrationを作らない。既存v2 DBをbackupした後に新規v3 DBを作り、Watchlistからfull discoveryで
再構築する。

v3以降のschema変更は `PRAGMA user_version` に基づく順次migrationを用意する。migration前にはSQLiteの
consistent backupを作成し、成功後にschema/integrityを検証する。

### 理由
現段階ではv2 local stateを移行する価値が低く、新規構築の方が実装と検証が単純である。一方v3では
CrawlRun/Artifact等の長期履歴を正本として持つため、それ以降はDB破棄を通常運用にできない。

