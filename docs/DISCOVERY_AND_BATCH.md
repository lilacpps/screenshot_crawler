# Discovery / Catalog / Batch Design

## Phase 4A status

The Manga ONE Discovery adapter and minimal `discover` CLI are implemented.
The adapter accepts any chapter URL, reads `#chapterList` newest-first, uses
`chapter_id` as stable source identity, and follows bounded 10-chapter `次へ`
pagination. `無料`/`FREE`, `先読`/`先読み`, and unbadged cards map to `free`,
`paid`, and `quota`. Uncertain traversal raises `DiscoveryIncompleteError`,
so missing-source reconciliation is not performed. BookWalker Discovery is
implemented as a series-scoped adapter; its current boundary is the explicit
series-list target described in 8.4.

## Phase 5A status

The read-only Batch Planner, Site Policy registry, Manga ONE Policy, and
BookWalker Policy are implemented. `batch plan` reads pending Catalog items
and creates candidates; it never runs the Crawler or changes Catalog state.
BookWalker uses a site-wide capacity of one quota start per 05:00 JST window.

## Phase 5B status

`batch run` is implemented for Manga ONE and BookWalker. It consumes the
Phase 5A plan in stable order, creates a site-neutral `RunConfig`, runs the
existing crawler, packages successful output, and then marks the item
completed. It is sequential and stops on the first failure. The plan command
remains fully read-only, while `batch run` may update local quota fields before
a quota crawl and item completion fields after successful packaging.

## 1. Status

この文書は、Discovery / Catalog / Batch Runnerの採用仕様を定める。

2026-09-19時点では、Watchlist + Catalog基盤、site-neutral Discovery framework、BookWalker series-scoped Discovery、Phase 5AのBatch Planner / Site Policy基盤 / Manga ONE Policy / BookWalker Policy、Phase 5BのManga ONE・BookWalker Batch Executor、BookWalker strict direct・quota entryが実装済みである。既存の `crawl --site --url` と `CrawlerRunner` のauto挙動は変更しない。BookWalker quotaの実サイトlive clickは未確認であり、synthetic/local CatalogでのBatch検証までを完了範囲とする。

実装済みの範囲:

- `watchlist.yaml` のload/validationとatomic write
- `watch list/add/remove/enable/disable` CLI
- SQLite Catalogの `items` / `sources` schema version 1
- `(site, external_id)` によるsource upsertとexternal state update
- Discovery upsert相当でのlocal completed state保護
- `RunConfig`への `access_strategy` / output metadata入力
- Adapterへのstrategy validation hook
- packagingのfield単位 `explicit > adapter > fallback` merge
- site-neutral Discovery model / Adapter contract / registry
- full / incremental Discovery Serviceとscope reconciliation
- cross-site duplicate warningの最小heuristic
- read-only Batch PlannerとSite Policy registry
- Manga ONEのlocal quota window / active grant判定
- Manga ONE Batch Executor、quota local state persistence、sequential run、packaging後のcompleted更新
- BookWalker Site Policy（05:00 JST / site-wide capacity 1）、grant-less quota state persistence、strict direct/quota Batch run

実装時は `docs/SPEC.md`、`docs/ARCHITECTURE.md`、`docs/DECISIONS.md` と本書をauthorityとして扱う。

## 2. 目的

現在のScreenshot Crawlerは、指定された1つの `site + URL` を安全にcrawlする責務に限定している。

追加するsubsystemの目的は次のとおり。

- 利用者が明示した作品だけをDiscovery対象にする
- 作品ごとの公開URL、無料状態、quota状態等を収集する
- Discovery結果をSQLite Catalogへ保存する
- Catalogから、現在取得可能なものだけをBatch Runnerが選ぶ
- Batch Runnerが実行条件を解決し、既存Screenshot Crawlerへ具体的なcrawl requestを渡す
- 同一作品が別siteに存在しても自動統合しない
- 期間限定無料やquotaを可能な限りsiteから再取得し、手動status管理を主経路にしない

万能なsite横断作品DB、全siteの無制限探索、完全自動の書誌照合は目的にしない。

## 3. 全体構成

```text
watchlist.yaml
  human-managed discovery targets
        ↓
Discovery Service
        ↓
Discovery Adapter
  site-specific listing logic
        ↓
Catalog Service
        ↓
catalog.sqlite
  items / sources
        ↓
Batch Runner + Site Policy
        ↓
Crawl Request
  site + URL + access strategy + optional metadata
        ↓
existing Screenshot Crawler
        ↓
ZIP / library
        ↓
Catalog update
```

重要な境界:

- Watchlistは「何を監視するか」の設定
- Catalogは「Discoveryした結果とlocal取得状態」の記録
- Discovery AdapterはDBを知らない
- CrawlerRunnerはDBを知らない
- Discovery ServiceとBatch RunnerだけがCatalogを利用する
- Site AdapterとDiscovery Adapterは別責務とする
- Site Policyはquota ruleを解決するが、Crawlerへquota rule自体は渡さない
- Crawlerへ渡すのは、今回の実行で必要な具体的な `access_strategy` と既知metadataだけとする

## 4. Watchlist

### 4.1 役割

Discovery対象は無制限に探索せず、`watchlist.yaml` に明示登録された起点だけに限定する。

Watchlistはhuman-managed configurationであり、Catalogの代替にはしない。

### 4.2 最小schema

```yaml
targets:
  - key: mangaone-example
    site: mangaone
    url: https://example.invalid/manga/1234
    enabled: true
    label: 作品A

  - key: bookwalker-example
    site: bookwalker
    url: https://bookwalker.jp/series/5678/list/
    enabled: false
    label: 作品B
```

fields:

- `key`: Watchlist内で一意なstable key。Discovery結果のscope識別にも使う
- `site`: Discovery Adapter名
- `url`: 作品ページ、シリーズページ等のDiscovery起点URL
- `enabled`: Discovery対象に含めるか。defaultは `true`
- `label`: 人間向け任意ラベル。identity authorityにはしない

`key` はURL変更後も維持する。full sync時のscopeを安全に特定するため、Catalogのsourceにも `discovery_key` として保存する。

### 4.3 操作

最低限、次を提供する。

```text
watch list
watch add
watch remove
watch enable
watch disable
```

YAMLの直接編集も許可する。

Watchlistからtargetをremove/disableしても、既存Catalog item/sourceは自動削除しない。

## 5. Catalog

### 5.1 方針

個人利用を前提として、SQLiteの**2テーブル**に限定する。

```text
items
sources
```

`works`、`crawl_jobs`、汎用event history等は初期実装では作らない。

### 5.2 items

`item` は実際に取得したい単位を表す。巻、話、章等を同じtableで扱う。

概念fields:

```text
id
canonical_title
author             # 取得できる場合。NULL可
genre              # packagingに利用できる場合。NULL可
kind               # volume / episode / chapter / book / other
order_key          # 正規化できる場合の巻数・話数等
order_label        # 第01巻、第12話など表示用
status             # pending / completed
local_path         # completed artifact。未取得ならNULL
completed_at
created_at
updated_at
```

`order_key` はsite間の完全照合を目的にしない。site内の安定した並び・重複判定に利用できる範囲で使う。

`canonical_title / author / genre / order_label` は、BatchからCrawlerへ既知metadataとして渡せる。NULLのfieldはCrawler側のSite Adapter取得値へfallbackする。

### 5.3 sources

`source` は1つのitemへアクセスできるsite上の場所と、その現在状態を表す。

概念fields:

```text
id
item_id
site
external_id
discovery_key
url
access_mode        # owned / free / quota / paid / unknown
free_until
available
access_checked_at
last_seen_at
quota_started_at
access_granted_until
created_at
updated_at
```

基本unique keyは、site側にstable IDがある場合:

```text
UNIQUE(site, external_id)
```

stable external IDが取れないsiteでは、Discovery Adapterがsite固有のstable source keyを生成する。URLそのものを恒久identityにはしない。

### 5.4 local stateとexternal state

Discoveryが更新してよいexternal state:

- `url`
- `access_mode`
- `free_until`
- `available`
- `access_checked_at`
- `last_seen_at`
- siteから取得したtitle/author/genre/order等のmetadata

Discoveryが変更してはいけないlocal state:

- `items.status = completed`
- `local_path`
- `completed_at`
- crawl成功/失敗の結果

`quota_started_at` と `access_granted_until` はBatch / Site Policyが管理するquota local stateであり、Discovery upsertやexternal state patchでは変更しない。新規sourceをDiscovery upsertするときは、これらをNULLで開始する。

原則:

```text
Discovery = external state synchronization
Batch/Crawl = local state update
```

## 6. 別siteの同一作品

### 6.1 自動統合しない

異なるsiteのitem/sourceを、自動で同一itemへmergeしない。

ISBN、title fuzzy matching等を使ったsite横断automatic identity resolutionは初期実装では行わない。

### 6.2 Discovery時の重複候補警告

新しいwatch targetをDiscoveryするとき、Catalog内の別site itemと明らかに近い候補があれば警告する。

候補判定には、取得できる範囲で次を利用する。

- normalized title
- `kind`
- `order_key` / `order_label`

この判定はheuristicであり、**warning only**とする。

```text
Possible duplicate on another site:
  current:  site-b / 作品A / 第01巻
  existing: site-a / 作品A / 第01巻
```

警告によって自動merge、自動削除、自動completed化は行わない。

既存local libraryをCatalogへ自動importする機能は初期実装の対象外である。Catalogに存在しない既存fileは、このwarningの対象にならない。

## 7. Discovery Adapter

### 7.1 責務

Discovery Adapterは、Watchlist targetのsite固有listing pageを読み、Discovery結果を返す。

担当するもの:

- 作品/シリーズページの解析
- item候補の列挙
- source URL / external ID取得
- title / author / genre / kind / order取得（取得可能な範囲）
- `access_mode` 判定
- `free_until` 判定可能なら取得
- `available` 判定
- full/incremental traversalに必要なsite固有navigation

担当しないもの:

- SQLite read/write
- cross-site merge
- Batch優先順位
- Screenshot Crawler実行
- local artifact state更新

### 7.2 Access mode

共通の最小分類:

```text
owned
free
quota
paid
unknown
```

意味:

- `owned`: 購入済み等でquotaなしに取得可能
- `free`: quotaなしで現在取得可能
- `quota`: site/workごとの回数枠等を消費して取得可能
- `paid`: 追加購入等が必要。Batch対象外
- `unknown`: 安全に判定できない。Batch対象外

期間限定無料は別modeを増やさず:

```text
access_mode = free
free_until = <known expiry>
```

とする。

site上で終了日時を取得できない場合、`free_until = NULL` を許容する。手動status上書きを標準運用にはしない。

## 8. Discovery mode

Discoveryは `full` と `incremental` の2modeを持つ。

実行頻度は本subsystemでは固定しない。外部schedulerまたは利用者が決める。

### 8.1 Full sync

`full` はWatchlist targetについて、現在列挙可能な全item/sourceを走査する。

用途:

- 初回Discovery
- 定期refresh
- 過去itemのfree/paid/quota状態変更検出
- URL変更の反映
- 期間限定無料の検出
- 公開終了sourceの検出

既存sourceを見つけた場合はINSERTせずUPSERTし、external stateを現在値へ更新する。

Full sync結果は最低限:

```text
results
complete: true / false
```

を持つ。

`complete=true` の場合だけ、同じ `discovery_key` に属する既存sourceのうち今回一度も観測されなかったものを:

```text
available = false
```

へ変更してよい。

`complete=false` の場合、未観測sourceをunavailableにしてはいけない。

sourceは物理削除しない。

### 8.2 Incremental sync

`incremental` は最新側から走査し、新しいitem/sourceと、走査範囲内で確認できた既存sourceのexternal stateだけを同期する。

既定の停止条件:

```text
異なる既知sourceが2件連続したら正常終了
```

既知sourceとは、stable source identityがCatalogに既に存在するものを指す。
ただし、site側のaccess状態遷移により「既知source 2件」が安全な境界にならない
場合は、Discovery frameworkに小さいsite-specific incremental stop hookを許容する。
defaultはこのknown-streak ruleを維持し、BookWalkerは8.4のstable-access boundaryを使う。

同一stable source identityの重複観測は連続known countを進めない。途中に未知sourceが現れた場合、連続known countと直前のknown identityは0へ戻す。

例:

```text
latest
  unknown -> add, known streak 0
  unknown -> add, known streak 0
  known   -> refresh, streak 1
  known   -> refresh, streak 2 -> stop
```

incremental syncでは、観測していない過去sourceを `available=false` にしない。

### 8.3 FullとIncrementalの関係

通常運用の想定:

```text
first discovery -> full
routine refresh -> incremental
periodic reconciliation -> full
```

頻度は仕様で固定しない。例えばweekly incremental等、運用側で設定できる。

### 8.4 BookWalker series-scoped Discovery

BookWalker Discoveryはsite全体や「まる読み10分」全対象を探索しない。
利用者がWatchlistへ明示登録したseries listだけを対象とする。

初期対応するtarget URL:

```text
https://bookwalker.jp/series/<series-id>/list/
```

series listは、そのtargetに属する商品の**grouping authority**とする。
同じlistに列挙された商品は、商品title文字列の推定結果にかかわらず同じ
Discovery group / packaging seriesとして扱う。購入特典、DJCD、番外編等が
listへ混在する場合も同じgroupには属するが、通常巻と推測してはいけない。

BookWalkerでのmetadata authority:

- `discovery_key`: Watchlist targetのstable `key`
- `external_id`: 商品URL `/de<uuid>/` のUUID
- `url`: 商品詳細ページURL
- `canonical_title`: non-emptyなWatchlist `label` があればそれを優先し、
  なければseries listのseries名を使う
- `kind`: 初期実装では `book`
- `order_key`: 通常巻・話として安全に数値化できる場合だけ設定
- `order_label`: 通常巻は正規化した巻表示。数値化できない特典・番外編等は、
  商品を識別できる短い表示を保持し、同名archive衝突を避ける
- author / genreはlistまたは商品ページから安全に取得できる場合だけ設定する

Discoveryはseries listから各商品を列挙し、必要な商品詳細ページを開いて
access controlを観測する。ただし**reader自体は開かない**。まる読み10分の
timerをDiscoveryで開始してはいけない。

BookWalker Discoveryはshared Crawler Chrome上のログイン済みsessionを前提とする。
ログアウト状態、login prompt、account状態不明等によりowned / quota判定を
安全に行えない場合は、最初のrecordをyieldする前に
`DiscoveryIncompleteError` とし、推測で `paid` や `unknown` を保存しない。
途中のDOM/navigation不明もincompleteとし、fullではmissing reconciliationをしない。

商品詳細ページのaccess分類は、強いsignalだけを使い次を採用する。

```text
owned
  購入済みのfull reader「読む」を強く確認できる

quota
  「まる読み10分」を強く確認できる
  data-action-label=read_maruyomi、またはvisible textの
  「まる読み」+「10分」等を使う

paid
  通常の「試し読み」だけを確認できる

unknown
  reader入口なし、購入特典等の特殊商品、unsupported subscription、
  または安全に分類できない状態
```

複数signalが同時にある場合の優先順位は:

```text
owned > quota > paid > unknown
```

`subscription_reading` というaction名だけでは `quota` と判定しない。
読み放題MAX等と「まる読み10分」を混同しないため、quotaには
maruyomi固有のvisible/action signalを必須とする。

BookWalker公式仕様では「まる読み10分」は1日合計10分で、AM5:00 JSTに
リセットされ、当日の10分終了後は対象作品でも通常の「試し読み」が表示される。
そのためBookWalkerのstable full-access stateは保守的に扱う。

```text
existing owned + observed quota/paid/unknown -> ownedを維持
existing quota + observed paid/unknown      -> quotaを維持
existing paid/unknown + observed quota      -> quotaへupgrade
any non-owned + observed owned              -> ownedへupgrade
```

trial観測だけで `quota -> paid` へdowngradeしてはいけない。
`available` はこのaccess-mode preservationとは別に、series list / productの
存在確認で更新する。

BookWalker incrementalはseries listのnewest側から走査するが、
genericなknown-source 2件では停止しない。採用停止条件は:

1. new sourceは商品ページを確認し、recordを同期して継続する
2. existing `paid` / `unknown` は商品ページを再確認し、継続する
3. **run開始前から** existing `quota` / `owned` だったsourceを1件確認したら、
   stable-access boundaryへ到達したものとして正常終了する
4. 今回のrunで `paid -> quota` へupgradeしたsource自身は停止境界にしない
5. stable boundaryがなければlist末尾まで走査する

incrementalでは未観測sourceをunavailableにしない。fullはseries list全体と
全商品詳細を走査し、clean exhaustion時だけ通常どおりmissing sourceを
`available=false` にできる。

同じBookWalker `external_id` が別のnon-null `discovery_key` にすでに所属する
場合、後から黙ってscopeを移動してはいけない。BookWalker Discoveryでは
scope conflictとしてincompleteにし、既存sourceの `discovery_key` /
`canonical_title` を上書きしない。

series list由来の `canonical_title` はBatchからCrawlerへexplicit metadataとして
渡す。これにより、商品ページ側のtitle推定が揺れても、同一series targetの
通常巻は同じseries directoryへpackageされる。

公式挙動の参照:
`https://help.bookwalker.jp/faq/3102`

## 9. Catalog upsert

Discovery ServiceはAdapterから返された結果をCatalogへupsertする。

概念フロー:

```text
Watchlist target
  ↓
Discovery Adapter
  ↓
DiscoveredItem / DiscoveredSource
  ↓
Discovery Service
  ↓
Catalog upsert
```

Adapter自身からSQLiteへ書き込まない。

upsert時:

1. `(site, external_id)` 等のsite-stable identityでsourceを検索
2. 既存ならexternal stateを更新
3. 新規ならitem/sourceを作成
4. 別siteの類似itemがあればwarningを出すがmergeしない
5. full + completeの場合のみmissing sourceをunavailable化

## 10. Site Policy

### 10.1 方針

「sourceが今どのaccess状態か」と「そのsiteでは何回利用できるか」を分離する。

```text
Source state
  free / quota / owned / ...

Site Policy
  quota limit
  quota scope
  quota consumption timing
  access grant duration
  site-specific eligibility
```

複雑なrule DSLやYAML rule engineは作らない。site-specific ruleが必要ならPythonの小さいPolicy実装に置く。

### 10.2 Quota

基本方針は、quotaを**crawl開始時に消費したものとして記録**する。

多くのsiteで、quota消費後に一定時間そのcontentを再閲覧できるケースを考慮する。

Catalogには最低限:

```text
quota_started_at
access_granted_until
```

を保持できるようにする。

例:

```text
crawl start at 2026-09-17 10:00
quota consumed
access_granted_until = 2026-09-18 10:00
```

その期間内のretry/re-crawlがsite上で追加quotaを消費しない場合、Policyは新しいquotaとして数えない。

ただし、quota scopeやgrant durationはsiteごとに異なり得る。

Policyは必要に応じて:

- site全体で1日N回
- 作品単位で1日N回
- source単位
- calendar-day reset
- rolling window
- grant duration（例: 24時間）

をsite固有codeで判断する。

初期実装で汎用quota rule engineは作らない。

Phase 5AのManga ONE Policyは、通常話1話を無料ライフ1個として扱う
local estimateを持つ。capacityは4、reset windowは09:00-21:00と
21:00-翌09:00のJST half-open interval、`quota_started_at` を同じ
window内で数える。`access_granted_until > now` のsourceはdirectであり、
quota slotを消費しない。grant durationは24時間として定義するが、
Phase 5Aではgrantを生成・永続化しない。Phase 5Bではquota crawl開始直前に
Policyのgrant期限を使って`quota_started_at`と`access_granted_until`を保存する。

このlocal estimateはCatalogが記録したquota消費だけを対象とする。利用者の
手動消費や別clientの実際のfree life残量は観測できない。

### 10.3 Access strategy

Catalogの `access_mode` はsourceの状態であり、Crawlerの今回の動作指定とは分ける。

Batch RunnerはSite Policyと `access_granted_until` 等を評価し、Crawlerへ次のsite-neutralな `access_strategy` を渡す。

```text
auto
  手動crawl等で利用。Site Adapterが従来どおりsite状態を観測して適切な入口を選ぶ。

direct
  新規quotaを消費しない前提でreaderへ入る。
  free / owned / quota消費後のgrant期間中など。

quota
  今回はquotaを利用してaccessを開始する意図を明示する。
```

例:

```text
source.access_mode = quota
access_granted_until > now
    -> access_strategy = direct

source.access_mode = quota
no active grant + quota eligible
    -> access_strategy = quota
```

Site Policyの `daily_limit` やreset ruleそのものをCrawlerへ渡さない。

`access_strategy` に応じたbutton選択、viewer entry等のsite固有操作はSite Adapterの責務とする。Manga ONE Adapterは`auto`/`direct`/`quota`を実行できる。BookWalkerは10.5のstrict entryを実装済みで、Batch Executorから`direct`/`quota`をAdapterへ渡す。Coreにsite名やquota button selectorの分岐を追加しない。

### 10.4 BookWalker Site Policy

BookWalker公式の「まる読み10分」はsite-wideで1日合計10分であるが、
初期Batch実装では秒単位の残時間最適化やresumeを行わない。
安全運用として**1 quota book / 05:00 JST window**をlocal policyとする。

window:

```text
05:00 JST <= now < 翌日05:00 JST
capacity = 1 quota start
scope = BookWalker site-wide
```

05:00より前は前日05:00から当日05:00までをcurrent windowとする。
同じwindow内のBookWalker `quota_started_at` を数え、1件記録済みなら
新しいquota candidateを選ばない。

このcapacity=1はBookWalker側の上限そのものではなく、Crawler側の
conservative local safety policyである。manual browser、別client、別端末での
まる読み利用はCatalogから観測できない。

BookWalker quota candidateは、実readerを開く前に `quota_started_at` を
永続化する。以後のcrawl / packagingが失敗しても同じwindow内では自動refundせず、
自動再試行しない。次の05:00以降に再試行する。

BookWalkerのまる読み10分には、Manga ONEのようなsource単位の24時間再閲覧grantを
仮定しない。BookWalkerでは `access_granted_until` をdirect判定の根拠にせず、
初期仕様ではNULLのまま扱う。実装時はBatch Executorを、quota policyが
grantを返さないsiteでも `quota_started_at` だけを安全に記録できるようにする。

`owned` sourceはquota capacityを消費せず `direct` として扱える。
`paid` / `unknown` はBatch対象外である。

運用上、BookWalker Discoveryはその日のまる読み利用前に行うのが望ましい。
Catalogにquota履歴がなくてもmanual利用は観測できないため、最終安全境界は
10.5のstrict quota entryとする。

### 10.5 BookWalker strict access strategy

BookWalker Site Adapterは既存manual crawl互換の `auto` と、
Batch用のstrict `direct` / `quota` を明確に分離する。

```text
auto
  現行のreader候補score/fallbackを維持する。
  手動crawlの互換経路。

quota
  「まる読み10分」の強い固有signalを持つcontrolだけを選ぶ。
  trial、購入済み「読む」、読み放題等へfallbackしない。

direct
  初期実装では購入済みfull reader「読む」の強いsignalだけを選ぶ。
  trial、まる読み10分、読み放題等へfallbackしない。
```

quota判定では `data-action-label=read_maruyomi`、またはvisible textで
「まる読み」かつ「10分」を確認する等、maruyomi固有signalを必須とする。
`subscription_reading` 単独はquota signalにしない。

requested strategyに合うcontrolが0件、複数で曖昧、または状態が不明な場合は
**click前に失敗**する。strict strategyからtrialへfallbackしてはいけない。
これによりtrial readerが正常ENDしてpartial contentをcompleted扱いする事故を防ぐ。

BookWalkerで将来 `free` full-readerをBatch対象にする場合は、free固有signalを
実サイト確認したうえで `direct` の許可条件を明示的に拡張する。
初期実装で「無料」「試し読み」等の曖昧な文字列からdirectを推測しない。

## 11. Batch Runner

### 11.1 責務

Batch RunnerはCatalogから現在取得可能なsourceを選び、Site Policyを評価して具体的なCrawl Request相当のBatch Planを作る。Phase 5Aでは既存Screenshot Crawlerへ渡さず、read-only結果として返す。Phase 5BのBatch Executorはcandidateを順番に実行し、crawl + packaging成功後にCatalogを更新する。

CrawlerRunnerへCatalog依存を追加しない。

概念フロー:

```text
pending item
  ↓
eligible sources
  ↓
Site Policy
  ↓
choose one source
  ↓
resolve access_strategy
  ↓
reserve quota slot in memory only
  ↓
build Batch Candidate
  ↓
Phase 5B: existing crawl / persistence
```

`BatchPlan.quota_available` is the local capacity before this plan's
reservations. `BatchPlan.quota_remaining` is the residual after the plan's
in-memory reservations; neither value is written to Catalog.

When more than one pending item needs a new quota consumption, the Planner
groups quota-consuming candidates by `source.discovery_key`. Groups are
processed in the first Catalog-registration order of each Discovery group,
using the minimum `source.id` in that group. Within a group, the Catalog
`order_key` is used as a generic natural-order key: numeric values are sorted
by number, and a recognized `-前編` / `-後編` suffix sorts as part 0 / part 1.
Unparseable or missing order keys use a stable `order_label` fallback and
`item.id` only as a final tie-breaker; they do not fail the whole plan.
Candidates whose source has `discovery_key = NULL` are placed after explicit
Discovery groups and use the same stable item-order fallback. This ordering
applies only to new quota-consuming candidates. `free`, `owned`, and quota
sources with `access_granted_until > now` remain `direct` and do not enter
the quota allocation pool. Items beyond the allocated slots are reported as
`quota_exhausted`.

### 11.2 Source priority

同一itemに複数sourceが明示的に存在する場合、基本優先順位は:

```text
1. free_untilが近いfree
2. 通常free
3. owned
4. quota
5. paid / unknown は対象外
```

同順位では安定した順序を使う。必要になった場合のみsite priorityを追加する。

異なるsite間のitemを自動で同一itemへmergeしないため、このpriorityは自動cross-site identity resolutionを意味しない。

### 11.3 Crawl success

正常なcrawl + packaging完了後に:

```text
items.status = completed
items.local_path = archive path
items.completed_at = now
```

を更新する。

Batch Runnerは、実行した `item_id` と `source_id` と生成されたarchive pathを対応付けられること。

失敗時は `completed` にしない。quota stateを保存した後のcrawl / packaging失敗でも、そのquota stateは消去しない。Catalog updateが失敗した場合も生成済みarchiveは削除しない。

### 11.4 Crawl Request

BatchからCrawlerへ渡す実行入力は、概念上次を持つ。

```text
site
url
access_strategy      # auto / direct / quota
output metadata      # optional
  title
  author
  order
  genre
```

`item_id` / `source_id` はCatalog orchestration上のidentityであり、CrawlerRunnerが理解する必要はない。Batch RunnerがrequestとCatalog rowの対応を保持する。

手動crawlでは:

```text
access_strategy = auto
output metadata = 未指定可
```

をdefaultとし、現在のURL-only運用を維持する。

## 12. Existing Screenshot Crawlerとの境界

既存CLI:

```text
crawl --site <site> --url <url>
```

および `CrawlerRunner` の1 URL -> 1 run責務は維持する。

新subsystemはその上位orchestration layerとする。

```text
Batch Runner knows Catalog
CrawlerRunner does not know Catalog
```

Crawler側は既存`RunConfig`を拡張してCrawl Request相当の `access_strategy` と任意metadataを受け取る。別の巨大なrequest objectはまだ作らない。

### 12.1 Access strategyの扱い

Crawlerの共通層は `access_strategy` をsite policyとして解釈しない。

- `auto / direct / quota` というsite-neutralな実行意図をrun contextとして保持する
- Site Adapterが必要なsite固有entry logicへ利用する
- Coreにsite-specific quota ruleやselectorを入れない

### 12.2 Output metadata override

Crawlerはtitle/author/order/genreを任意入力として受け取れるようにする。

packaging metadataは**field単位**で次の優先順位とする。

```text
1. Crawl Requestの明示metadata（non-empty）
2. Site Adapterが `get_output_metadata()` 等で取得した値
3. packaging側の既存fallback
```

例:

```text
request.title = 作品A
request.order = 第12巻
request.author = NULL

adapter.title = サイト上の別表記
adapter.order = 第12巻
adapter.author = 作者A

resolved:
  title  = 作品A
  order  = 第12巻
  author = 作者A
```

Crawlerは明示metadataが欠けていても失敗せず、従来どおりsiteから取得を試みる。

source URLやmanifestの実URLはこのmetadata overrideで置換しない。

## 13. CLI案

名称は実装時に既存CLIとの整合を確認するが、最低限のcapabilityは次とする。

```text
watch list
watch add --key ... --site ... --url ... [--label ...]
watch remove --key ...
watch enable --key ...
watch disable --key ...

discover --key KEY --mode full|incremental
discover --all --mode full|incremental

catalog list [...filters...]

batch plan --site ... [--catalog ...]
batch run [...filters/limit...]  # Phase 5B
```

既存 `crawl` には、実装時に必要最小限のoptional inputを追加できる。

```text
crawl --site ... --url ...
      [--access-strategy auto|direct|quota]
      [--title ...]
      [--author ...]
      [--order ...]
      [--genre ...]
```

defaultは `access_strategy=auto`、metadata未指定とし、既存CLI互換を維持する。

Watchlist全件実行時は `enabled=true` のtargetだけを対象とする。

`discover` のtarget selectorは `--key KEY` と `--all` のmutually exclusive
required groupである。`--all` は `WatchlistService.list_targets()` のfile
orderを維持し、`enabled is True` のtargetだけを順番にDiscoveryへ渡す。
disabled targetはDiscovery Serviceへ渡さず、Catalogにも副作用を与えない。

`--all` は単なるCLI orchestrationであり、各targetについて既存の
`DiscoveryService.discover(page, target, mode)`を呼び出す。targetごとに
CDP endpointを既存の優先順位で解決し、BrowserSessionをconnect、Pageを
作成してDiscovery後にPageをcloseし、BrowserSessionをdisconnectする。
`--cdp-endpoint`は全targetで優先される。Crawler Chromeの自動起動は行わない。
Crawler Chromeは事前起動が必要であり、BatchはDiscoveryとは別コマンドである。

`--all` はtargetの失敗を収集して後続targetを続行し、最後にmode、target数、
成功数、失敗数と失敗理由を表示する。例外failureに加えて、DiscoveryResultの
`stopped_reason=incomplete`もtarget failureとして扱う。後続targetは続行し、
1件以上失敗した場合はCLI全体がnon-zero exitとなる。全成功またはenabled target
0件は正常終了する。`--all --keep-open`
はtarget単位で接続を閉じるlifecycleと両立しないためCLI validationで拒否する。

## 14. Failure / Safety

- Watchlist外の作品を無制限探索しない
- Discovery Adapterの不明状態を推測でfree扱いしない
- `unknown` / `paid` は自動crawlしない
- full syncがincompleteならmissing sourceをunavailable化しない
- incrementalで未観測sourceをunavailable化しない
- source URLが変わってもstable external IDが同じなら同一sourceとして更新する
- cross-site duplicate heuristicはwarning only
- Discoveryでlocal completed stateを消さない
- crawl失敗をcompleted扱いしない
- quota消費記録はcrawl開始前後のcrashでも矛盾しにくい順序で永続化する
- active grantがあるquota sourceを新規quota消費として二重計上しない
- Batchがquota ruleそのものをCrawlerへ押し込まない
- Crawlerのmetadata overrideでmanifest/source URLを偽装しない
- Watchlist removeでCatalogをcascade deleteしない
- `batch plan` は `items.status`、`local_path`、`completed_at`、`quota_started_at`、`access_granted_until` を変更しない
- planner内のquota仮予約をCatalogへ永続化しない
- BookWalker Discoveryでreaderを開いて10分timerを開始しない
- BookWalkerの既知quota/ownedをtrial/unknown観測だけでdowngradeしない
- BookWalker `quota` strategyからtrial/owned/subscriptionへfallbackしない
- BookWalker `direct` strategyからtrial/maruyomi/subscriptionへfallbackしない
- BookWalkerの同一external_idを別discovery_keyへ黙って移動しない
- BookWalker quota crawl失敗後に同じ05:00 windowで自動再試行しない

## 15. Acceptance Criteria

### Watchlist

- targetをadd/remove/list/enable/disableできる
- `key` が一意である
- disabled targetは通常Discovery対象にならない
- remove/disableで既存Catalog dataを削除しない

### Discovery

- Watchlist targetだけを探索する
- AdapterはSQLiteを直接操作しない
- full syncで新規sourceを追加できる
- full syncで既存sourceのURL/access/free_until等を更新できる
- complete full syncだけがmissing sourceをunavailable化する
- incomplete full syncで既存sourceを誤ってunavailable化しない
- incrementalはlatest側から走査する
- default incremental policyはknown source 2件連続で停止する
- site固有のstable boundaryが必要な場合は小さいoverrideを許容する
- incrementalで新規sourceを取りこぼさず追加できる
- incrementalは未観測過去sourceをunavailable化しない
- 別siteの類似itemはwarningし、自動mergeしない
- title/author/genre/orderを取得できるsiteではCatalog metadataへ反映できる

### Catalog

- `items / sources` の2テーブルで運用できる
- sourceはstable site identityでupsertできる
- Discovery external stateとlocal completed stateを分離できる
- Watchlist `key` とsourceのDiscovery scopeを対応付けられる
- packaging用metadataをNULL許容で保持できる

### Batch

- paid/unknownを自動crawlしない
- free/owned/quotaをPolicyに従って選択できる
- 期限付きfreeを期限の近い順に優先できる
- quotaをcrawl開始時に記録できる
- site固有のaccess grant期間中は必要に応じて追加quotaを消費せずretryできる
- source stateとgrant状態から `access_strategy=direct|quota` を解決できる
- Site Policyのquota rule自体をCrawlerへ渡さない
- crawl成功時だけitemをcompletedへ更新する
- `item_id / source_id / archive path` を対応付けられる
- Catalogにあるmetadataをoptional overrideとしてCrawlerへ渡せる
- CrawlerRunner自体はCatalogを知らない

### Crawler integration

- 手動crawlのdefaultは `access_strategy=auto` で既存挙動を維持する
- `access_strategy` をSite Adapterのsite固有entry logicへ伝えられる
- Coreにsite-specific quota ruleを追加しない
- title/author/order/genreをoptional inputとして受け取れる
- metadataは `explicit request > adapter > fallback` のfield単位優先順位で解決する
- 一部metadataだけ指定しても残りをAdapterから補完できる
- metadata未指定なら従来どおりAdapter取得を利用できる

### BookWalker

- Watchlistの `/series/<id>/list/` targetだけをDiscoveryする
- series list内の商品をtitle推定ではなく同一Discovery groupとして扱う
- series由来canonical_titleをBatch explicit metadataとして同一series packagingに使う
- Discoveryは商品詳細のcontrolを観測するだけでreaderを開かない
- owned / quota / paid / unknownを強いsignalで分類できる
- `subscription_reading` 単独をquota扱いしない
- trialだけの既存paid/unknownをincrementalで再確認できる
- run開始前からquota/ownedだった既知sourceをstable boundaryとしてincremental停止できる
- quota/ownedをtrial/unknown観測だけでdowngradeしない
- same external_id / different discovery_key conflictを黙って上書きしない
- BookWalker Policyは05:00 JST区切りでlocal quota 1冊/日を選択する
- quota attemptはcrawl前に記録し、失敗しても同windowで自動再試行しない
- BookWalkerで `access_granted_until` をdirect根拠にしない
- `quota` strategyはまる読み10分以外をclickしない
- `direct` strategyは初期実装で購入済みfull reader以外をclickしない
- strict entry失敗時にitemをcompletedにしない

## 16. 初期実装の非対象

- 全site・全作品の無制限Discovery
- site横断automatic item merge
- ISBN等を使った完全な書誌identity
- 既存local libraryの自動Catalog import
- GUI
- 汎用rule DSL
- 汎用quota engine
- 複雑なcrawl job history
- 複数site parallel batch
- 自動購入
- CAPTCHA / MFA回避
- schedulerそのものの実装
- BookWalkerの10分を秒単位で使い切る複数冊最適化
- BookWalkerの途中停止巻を翌日同じrunへresumeする機能
