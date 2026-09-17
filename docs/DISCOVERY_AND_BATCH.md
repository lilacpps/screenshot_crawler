# Discovery / Catalog / Batch Design

## 1. Status

この文書は、Discovery / Catalog / Batch Runnerの採用仕様を定める。

2026-09-17時点では、Watchlist + Catalog基盤、Crawl Requestの最小基盤、site-neutral Discovery frameworkが実装済みである。BookWalker/Manga ONE Discovery Adapter、Batch Runner、Site Policy、site-specific direct/quota behaviorは未実装である。既存の `crawl --site --url` と `CrawlerRunner` のauto挙動は変更しない。

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
    url: https://example.invalid/series/5678
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

停止条件:

```text
異なる既知sourceが2件連続したら正常終了
```

既知sourceとは、stable source identityがCatalogに既に存在するものを指す。

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

`access_strategy` に応じたbutton選択、viewer entry等のsite固有操作はSite Adapterの責務とする。現時点の既存Adapterは`auto`だけを実行でき、未対応の`direct`/`quota`は明示的に停止する。Coreにsite名やquota button selectorの分岐を追加しない。

## 11. Batch Runner

### 11.1 責務

Batch RunnerはCatalogから現在取得可能なsourceを選び、Site Policyを評価して具体的なCrawl Requestを作り、既存Screenshot Crawlerへ渡す。

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
record quota start/grant if newly consuming quota
  ↓
build Crawl Request
  ↓
existing crawl
  ↓
success -> item completed + local_path
failure -> item remains pending
```

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

失敗時は `completed` にしない。

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

discover --mode full [--key ...] [--site ...]
discover --mode incremental [--key ...] [--site ...]

catalog list [...filters...]

batch run [...filters/limit...]
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
- incrementalはknown source 2件連続で停止する
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
