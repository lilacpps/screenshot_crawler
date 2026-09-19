# 00. Core 現行実装ノート

## Phase 4A Discovery status

`MangaOneDiscoveryAdapter` is now registered for `mangaone`. It reads an
arbitrary chapter URL's `#chapterList` newest-first, follows bounded 10-item
pagination, and uses the chapter id (not the URL) as source identity.
`無料`/`FREE`, `先読`/`先読み`, and unbadged cards map to `free`, `paid`, and
`quota`. Incomplete traversal is not treated as a complete full scan. The
adapter remains Catalog-free and does not own BrowserSession lifecycle; the
minimal `discover` CLI supplies the Page. BookWalker series-scoped Discovery
is now registered. BookWalker Site Policy, grant-less quota consumption, and
automatic Batch execution are implemented, while BookWalker strict
direct/quota product-page entry remains in the BookWalker Adapter. Phase 5A adds
read-only Batch planning and Manga ONE Policy. Phase
5B adds sequential Manga ONE Batch execution around the existing Core.

このファイルはScreenshot Crawler Coreの**現在の実装詳細**と、採用済みのBrowser Session移行方針をまとめる。Core / Runner / browser / output / packaging / diagnostics / resume方針を変更した場合は、このnoteも同じ変更で更新する。

最終同期: 2026-09-19

## 1. Scope

Coreはサイト固有DOMやページ送りを判断しない。共通処理を担当する。

主な責務:

- Playwright browser/context接続補助
- URL navigation
- Site Adapter呼び出し
- PageState loop
- capture / artifact保存（default PNG、Adapter direct captureではformat metadataを保持）
- SHA-256 fingerprint
- duplicate / same-content guard
- manifest / progress
- diagnostics
- max_pages / retry / timeout
- 正常終了後のZIP packaging

Site固有selector、END判定、NEXT操作は `site_adapters/<site>/` の責務。

## 2. Main modules

```text
src/screenshot_crawler/core/
├─ browser.py       browser launch / CDP endpoint / CDP connection / session
├─ capture.py       Locator / canvas capture, artifact save
├─ diagnostics.py   screenshot / HTML / metadata / error
├─ errors.py        crawler errors
├─ fingerprint.py   SHA-256
├─ models.py        RunConfig / identity / context / captured page
├─ packaging.py     manifest-based ZIP / library output
├─ progress.py      manifest / progress / new-run safety
├─ runner.py        state machine
└─ state.py         PageState
```

`site_adapters/base.py` がAdapter contract。

## 3. Browser Session Model

### 3.1 採用済みの目標仕様

Real-site automationは、1つの共通Crawler Chrome/profileへCDP接続し、そのChromeをPlaywrightで操作する。

```text
Crawler Chrome
└─ .chrome-crawler/
      ├─ bookwalker.jp session
      ├─ manga-one.com session
      └─ other site sessions
          ↑
          │ CDP
          ↓
Playwright Browser / Context / Page
          ↓
Core Runner
          ↓
Site Adapter
```

役割:

- CDP = Chromeへの接続transport
- Playwright = 通常のbrowser/site操作API
- Adapter = site固有viewer logic

Raw CDP ProtocolはPlaywrightで代替できない場合だけ使う。

### 3.2 現行実装

real-siteの標準launcherは `scripts/start_crawler_chrome.ps1` である。repository root基準の
`.chrome-crawler/` profileを使い、default port `9222`でshared Crawler Chromeを起動する。
指定portに既存CDP listenerがある場合はChrome processのcommand lineでportとshared profileを確認する。一致すれば既存Chromeを再利用し、一致しない・確認できない場合は二重起動せずerrorで停止する。

起動時の `--user-data-dir` はquoteして渡す。起動後も `/json/version` 応答だけを成功条件にせず、同じprocess確認を再実行し、remote debugging portとshared profileの一致を確認してから成功メッセージを表示する。

```text
scripts/start_crawler_chrome.ps1
.chrome-crawler/
```

BookWalker/Manga ONEのshared-profile live verificationが完了しているため、real-site launcherはこの共通launcherのみを標準とする。移行前に作成されたsite-specific profile directoryが残っていても、launcherは自動削除しない。

現行CLIのendpoint解決も:

```text
--cdp-endpoint
→ site-specific *_CDP_ENDPOINT
→ CRAWLER_CDP_ENDPOINT
→ http://127.0.0.1:9222
```

で統一されている。CLI指定を最優先し、site-specific endpointは例外overrideとして
維持する。`.env`の値よりプロセス環境変数が優先される。

Phase 1/2では、次を実装済みである。

```text
CRAWLER_CDP_ENDPOINT
core.browser.resolve_cdp_endpoint()
core.browser.BrowserSession
```

`CRAWLER_CDP_ENDPOINT` はshared Crawler Chromeを指す標準global endpointである。
site-specific endpointは特殊なprofile/account等のための例外overrideとして残している。

既存CDP listenerがある場合、launcherはprocess command lineのremote debugging portと
`--user-data-dir`をshared profileと照合する。一致しない、またはprocessを確認できない場合は
既存Chromeを黙って再利用せずerrorで停止する。

### 3.3 移行時の非変更範囲

Browser Session統一のために以下を変更しない。

- BookWalker capture方式
- BookWalker END/NEXT_CONTENT
- Manga ONE capture方式
- Manga ONE image-disappearance END heuristic
- Runner fingerprint dedupe
- output/packaging semantics

Browser/session管理だけを差し替える。

## 4. Authentication model

login sessionのauthorityは共通Chrome profile。

Chrome自身がsiteごとに:

- Cookie
- localStorage
- IndexedDB
- その他browser storage

を保持する。

Crawlerはsite別storage-state JSONを標準管理しない。

login CLIは:

```text
Browser Session Layer
→ Playwright Page
→ site-specific login handler
```

で動く。

real-siteのcrawl/loginは `BrowserSession.connect()` でCDP接続し、既存の
BrowserContextからPageを作成する。crawlが作成した作業Pageは終了時に閉じる。
loginは別siteの既存タブを再利用せず、常にlogin用new Pageを作成して終了時に閉じる。
BrowserSessionの終了はPlaywright接続を切断するだけで、remote Chrome processは閉じない。

Probeのnative Playwright launchでは `launch_browser()` / `create_browser_context()` を使う。
`connect_browser()` と `close_browser()` はProbeおよびBrowserSessionで使うため残している。
repository-wideでcall siteがなかった `BrowserSession.existing_page()` と `create_page()` は削除した。
保存済みauth-stateの補助 (`auth.storage` / `save_auth.py`) もProbe・local auth workflowで到達可能なため、
real-site標準がChrome profileであることだけを理由に削除しない。

credentialsのinputは `.env` 等を使ってよいが、session保存はChromeへ任せる。

CAPTCHA / MFA / validation errorは自動突破しない。

## 5. CDP endpoint policy

現行の優先順位:

```text
--cdp-endpoint
→ <SITE>_CDP_ENDPOINT
→ CRAWLER_CDP_ENDPOINT
→ http://127.0.0.1:9222
```

通常はglobal endpointだけを使う。

site-specific overrideは例外用:

- 別account
- extension差
- browser setting差
- session分離
- 共通profileでは正常動作しない場合

## 6. Adapterとの境界

Adapterへ渡るものはPlaywright `Page`。

Adapterは:

- Locator取得
- click / keyboard / mouse
- wait
- evaluate
- capture target決定
- END / NEXT_CONTENT判定

を行う。

Adapterは:

- Chrome launch
- profile選択
- endpoint解決
- `connect_over_cdp()`
- BrowserContext lifecycle

を行わない。

## 7. PageState loop

PageState:

```text
CONTENT
AD
END
NEXT_CONTENT
LOADING
UNKNOWN
```

Runner概念フロー:

```text
ensure output dir is new/empty
prepare_page
page.goto
adapter.initialize
initial context
ProgressStore作成

loop:
    detect state

    END / NEXT_CONTENT
        -> normal return

    UNKNOWN
        -> error + diagnostics

    AD
        -> go_next + wait_for_change

    CONTENT
        -> max_pages guard
        -> context確認
        -> identity取得
        -> one/multiple capture targets取得
        -> capture
        -> fingerprint dedupe
        -> artifact bytes + manifest/progress保存
        -> go_next + wait_for_change
```

LOADINGはbounded retryし、解消しなければ `PageChangeTimeoutError`。

## Adapter timeout layering

`RunConfig.page_change_timeout_ms` is the adapter-owned operation deadline. The
Core `CrawlerRunner._adapter_call()` wrapper uses the same deadline plus
`adapter_timeout_grace_ms` (default 2,000 ms). This keeps the Core guard for a
hung adapter while allowing an adapter such as BookWalker to raise its own
`PageChangeTimeoutError` first, instead of being cancelled by an equal outer
`asyncio.wait_for()` timeout. The grace applies to all adapter calls and does
not add a site-specific branch.

## 8. max_pages

`max_pages` は保存ページ数の安全上限。

重要な境界仕様:

- `saved == max_pages` のあと次stateが `END` / `NEXT_CONTENT` → 正常終了
- `saved == max_pages` のあとさらに `CONTENT` → `MaxPagesExceededError`
- `max_pages`を超えるPNGは保存しない

## 9. Identity / fingerprint / duplicate

`ContentIdentity` はpage id / page number / source id等を保持し、主に:

- Adapter change detection
- manifest
- debug / progress

へ使う。

**保存duplicateのauthorityはcapture bytesのSHA-256 fingerprint。**

identityが異なっていてもfingerprintが同一ならduplicate扱い。

これは既存BookWalker / Manga ONEの動作互換を優先した現行仕様。

## 10. same-content guard

新しいcaptureが得られない状態が続いた場合は `same_content_count` を増やす。

既定 `max_same_content = 3`。

上限到達で `PageChangeTimeoutError` として停止する。

## 11. Context / NEXT_CONTENT

開始時 `ContentContext` と現在contextのstrong fieldを比較する。

strong fields:

- content_id
- work_id
- episode_id
- chapter_id

同じfieldが開始時・現在とも存在し、値が変わった場合だけcontext change。

optional情報が後から埋まっただけではNEXT_CONTENTにしない。

## 12. Capture

基本はLocator単位capture。

Canvas targetの場合、`capture.py` はcanvas raw PNG bufferを取得できる。

Adapterは `get_capture_targets()` で複数targetを返せる。保存順はAdapterが返した順。

一時targetは `cleanup_capture_targets()` で後始末する。

Adapterは必要な場合だけ `capture_page(page)` をoverrideできる。非`None`の非空
`tuple[CaptureResult, ...]`を返した場合、CoreはLocator captureを行わず、その結果を同じ
fingerprint / manifest / page dimension処理へ渡す。`None`、`CaptureUnavailableError`、Coreの
bounded timeoutでは従来の `get_capture_targets()` → `capture_locator()`へfallbackする。
fallback後のcapture失敗は通常のrun errorとし、直接capture hookが作ったtemporary resourceの
cleanupはhook側の責任とする。Base Adapterは`None`を返すため、overrideしないsiteの挙動は維持する。

## 13. Run output safety

新規runの `output_dir` は、存在しないか完全に空でなければならない。

既存ファイルが1つでもある非空directoryは `RunAlreadyExistsError` で拒否する。

目的:

- 前runのcapture artifact混入防止
- manifest/progress上書き防止
- user file削除防止

`ProgressStore` も既存manifest/progressを暗黙上書きしない。

## 14. Manifest / progress

実行中:

```text
<output_dir>/
├─ page-0001.png  # default Locator capture
├─ page-0002.webp # source-native Adapter captureの例
├─ manifest.json
├─ progress.json
└─ diagnostics/  # failure時に作られる場合あり
```

manifestは保存ページ一覧のauthority。

各page entryは `mime_type` と `file_extension` を持つ。Locator / canvas captureの
defaultは `image/png` / `.png` で、Adapterのdirect captureはsource-native artifactの
formatをそのまま記録できる。Runnerはこのextensionで連番ファイル名を生成し、
packagingはmanifest記載の安全なPNG/WebP artifactだけを対象にする。

`progress.json` はlast sequence / identity / fingerprint / contextを持つが、**自動resume機能ではない**。

JSON更新はtemporary file → `os.replace`。

## 15. Resume

現行ではresume未実装。

- 非空run dirは拒否
- 既存manifest/progressを読み込んで続行しない
- 暗黙resumeしない

将来追加するなら `--resume` 等で新規runと明示的に分離する。

## 16. Packaging

正常な `END` / `NEXT_CONTENT` 後だけZIP化する。

ZIP対象はdirectory globではなく `manifest.json` の `pages[].file` がauthority。

安全ルール:

- manifest外artifactをZIPへ入れない
- manifest記載artifact欠落はfail
- unsafe path拒否
- manifest file重複指定拒否
- 既存同名ZIPは上書きしない

ZIPはlibrary treeへ保存し、completion status JSONを別途残す。

## 17. Intermediate directory cleanup

ZIP作成後、source crawl directoryを削除するのは、directory内容が次だけの場合に限る。

- `manifest.json`
- `progress.json`
- manifest記載page artifact

余分なartifact、diagnostics、user file、その他directoryがあればsource全体を `rmtree` しない。

失敗runは残す。

## 18. Diagnostics

現在の `write_diagnostics()` が保存するもの:

```text
screenshot.png
page.html
metadata.json
error.txt
```

既知の制約:

- diagnostics pathはrun-specific subdirectoryを自動生成しない
- `SiteAdapter.collect_debug_metadata()` hookはcontractにあるがRunner未統合
- diagnostics保存失敗は元例外を隠さない

## 19. CLI / packaging flow

現行real-site crawl:

```text
CLI
 -> endpoint resolution
 -> BrowserSession.connect()
 -> existing BrowserContext
 -> crawler/login Page
 -> CrawlerRunner.run
 -> END / NEXT_CONTENT
 -> crawler Page close
 -> package_crawl_output
 -> Crawler Chromeは残す
```

主なcrawl引数:

```text
--site
--url
--output-dir
--diagnostics-dir
--library-dir
--max-pages
--max-same-content
--access-strategy auto|direct|quota
--title
--author
--order
--genre
--env-file
--cdp-endpoint
--keep-open
```

2026-09-17時点で、`access_strategy` とoutput metadata override用のCLI/API inputは実装済みである。manual crawlのdefaultは`auto` + metadata未指定で、従来のURL-only挙動を維持する。

現行のRunConfigは、概念上のCrawl Request入力として次を保持する。

```text
access_strategy = auto / direct / quota
optional output metadata:
  title
  author
  order
  genre
```

手動crawlのdefaultは `auto` + metadata未指定とし、現行挙動を維持する。

## 20. Tests

Unit testsで主に確認するもの:

- fingerprint
- capture
- Runner guards
- max_pages境界
- duplicate / same-content
- progress safety
- packaging / manifest validation
- site parser/helper

Browser Session共通化で現在確認しているもの:

- endpoint precedence（CLI > site override > global > default）
- BookWalker / Manga ONEが同じresolverを使うこと
- shared context/page取得
- remote Chromeをcloseしない
- login/crawl共通BrowserSession
- Adapterがbrowser接続方式へ依存しない

2026-09-17にshared `.chrome-crawler/`でBookWalker/Manga ONEのlogin・crawl・session共存を確認済みである。
loginは既存tabを再利用せず専用new Pageを使い、Pageだけをcloseしてremote Chromeを維持する。
両siteのcapture・navigation・END behaviorに回帰はない。

## 21. Known maintenance items

- `BrowserSession`の不要Page helper再発防止
- explicit resume
- Adapter `collect_debug_metadata()` のRunner統合
- diagnostics run directory分離
- config.yaml整理
- identity/fingerprint dedupe再検討
- GitHub CI
- tracked `.egg-info` 整理

これらを変更した場合は、このnoteを必ず更新する。

## 22. Discovery / Catalog / Batch（Watchlist + Catalog + Discovery + Batch v3実装済み）

2026-09-19時点では、Watchlist + Catalog基盤、Crawl Requestの最小基盤、site-neutral Discovery framework、BookWalker series-scoped Discovery、Phase 5Aのread-only Batch Planner / Site Policy registry / Manga ONE・BookWalker Policy、Phase 5BのManga ONE・BookWalker Batch Executor、BookWalker Adapterのstrict direct・quota product-page entryが実装済みである。BookWalkerは05:00 JSTのsite-wide 1枠local safety policyを使い、quota開始をreader entry前に永続化する。実サイトquota clickは未確認である。

authority:

- `docs/SPEC.md`
- `docs/ARCHITECTURE.md`
- `docs/DISCOVERY_AND_BATCH.md`
- `docs/DECISIONS.md`

### 22.1 Watchlist（実装済み）

`WatchlistService`（`src/screenshot_crawler/watchlist/`）がhuman-managed `watchlist.yaml`を扱う。既定pathはcurrent directoryの`watchlist.yaml`で、CLIの`watch`配下では`--watchlist`でoverrideできる。schemaは`targets` listとrequired `key` / `work_key` / `site` / `url` / `label`、optional `enabled`（default `true`）である。required textは空文字を許さず、keyはlist内で一意で、duplicate・malformed YAML・不正targetは明示エラーにする。

CLIは`watch list`、`watch add`、`watch remove`、`watch enable`、`watch disable`を提供する。書き込みは同一directory内のtemporary fileをfsyncして`os.replace`する。Watchlist操作はCatalogを読み書きせず、remove/disableでもCatalog rowを削除しない。

### 22.2 Catalog（Schema v3 Phase 1実装済み）

`CatalogService`（`src/screenshot_crawler/catalog/`）がSQLite connection lifecycle、foreign key enforcement、schema initialization、v3 CRUDを集約する。既定DB pathは`catalog.sqlite`で、`initialize()`または最初のservice operationで初期schemaを作成する。Schema v2 DB、v1 DB、未知のversionはmigrationせず拒否する。v2からの再構築はbackup後にfull discoveryで行う。

Schema v3のdomain tableは`works`、`items`、`sources`、`source_targets`、`crawl_runs`、`artifacts`の6つを持つ。Workがstableな`work_key` / title / author / genreを保持し、ItemはWork配下の取得単位として`item_title`、kind、order、statusを保持する。v2の`canonical_title`、Itemのauthor/genre、`local_path`は存在しない。Itemの`completed`は運用上の取得済み状態で、Artifactの移動・missing・deletedではpendingへ戻さない。

`Source`のidentityは`(site, external_id)`で、access stateとquota local stateを分離する。`update_source_external_state()`はquota stateを変更せず、`record_quota_access()`はquota stateだけを更新し、`mark_sources_unavailable_except()`は指定Discovery scope内のmissing sourceだけをunavailable化する。

`source_targets`はopaqueな`backend` / `target_key` / `locator`を保持し、identityは`(source_id, backend, target_key)`である。`CatalogService`はcreate/upsert/find/get/listを提供するが、target selectionやlocatorの解釈は行わない。

`crawl_runs`はItem/Source/Targetの整合性を検証して作成時snapshotを保存し、`running -> succeeded|failed`だけを許可する。`artifacts`はbinary本体を保存せず、SHA-256、byte size、storage backend、locator、stateを保持する。手動importのためcrawl runなしを許容し、Artifact更新はItem/CrawlRun statusを変更しない。

Phase 1でCatalog packageをv3へ移行し、Phase 2でWatchlist / DiscoveryをWork-aware化し、Phase 3でBatch Planner / ExecutorをCrawlRun / Artifactへ接続した。Catalog Exportは後続Phaseの対象である。

Batch Planner用に `read_works_items_sources_and_targets(site=...)` を提供する。これはread-only接続でWork / Item全件、指定siteのSource、関連するSourceTargetを取得し、Plannerはraw SQLiteへ直接アクセスしない。指定siteのSourceを1件以上持つItemだけをsite-scopedな母集団にし、別site専用Itemとsourceなしのorphan Itemを`no_source` skipに含めない。未存在・未初期化Catalogを作成せず、Batch planによるCatalog副作用を防ぐ。

Catalog確認用に `catalog export` CLIを提供する。`catalog/export.py` の `export_catalog_csv()` がSQLiteをread-onlyで検証・読み込みし、`items LEFT JOIN sources LEFT JOIN source_targets` を `item_id ASC, source_id ASC, target_id ASC` で並べたflat CSV snapshotを生成する。原則1行は1 targetで、sourceにtargetがない場合とsourceなしitemも情報を残す。CSVはUTF-8 BOM、header付きで、NULLは空欄、`available` と `target_enabled` は `true` / `false` とする。既定pathは入力 `catalog.sqlite`、出力 `catalog-export.csv` であり、CSVからCatalogへ戻す機能はない。旧`url`列は出力しない。

日時は`catalog.service.now_jst()`で生成するaware fixed-offset JST timestampを、ISO 8601の`+09:00`文字列として保存する。naive datetimeは拒否する。schema versionはSQLite `PRAGMA user_version`の`3`だけをサポートし、v1/v2/未知versionはmigrationせず明示的に失敗する。v3では6 tables、required columns、v2 removed columns不存在、`source_targets.target_key`を検証する。Alembic等のmigration frameworkは導入していない。

採用した上位flow:

```text
watchlist.yaml
    ↓
Discovery Service / Discovery Adapter
    ↓
catalog.sqlite (works / items / sources / source_targets)
    ↓
Batch Runner / Site Policy
    ↓
Crawl Request
    ↓
既存CrawlerRunner
```

現行実装には、BookWalker quotaの実サイトlive click検証と、quotaのサーバー側実消費をCatalogだけから検証する機能は存在しない。

Watchlist CLI、Catalog Service、Work-aware Discovery framework、Crawl Request最小基盤、Schema v3 Batch Planner / Executor、Site Policy registry / Manga ONE・BookWalker Policyは実装済みである。Discoveryはtargetの`work_key`でWorkをfind/createし、`label`は新規Workのtitle初期値にだけ使う。新規recordはWork配下にItem、Source、web/default targetを原子的に作成し、既存recordはItemを再利用する。Batch PlannerはWork metadataとItem order metadataからcandidateを生成し、enabledなweb targetを`priority ASC, target.id ASC`で選ぶ。Batch Executorはstale validation後にCrawlRunを作成し、quota記録、Crawler、packaging、Artifact / Run / Itemの成功確定を順序づける。現行CrawlerRunnerへCatalog read/writeは追加せず、1 URL -> 1 run責務を維持する。

主要仕様:

- Discovery対象は明示Watchlistだけ
- Watchlist targetはstable `key` と明示的な `work_key` / `label` を持つ
- Catalog v3 Phase 3は `works / items / sources / source_targets / crawl_runs / artifacts` の6テーブル
- full syncはcomplete時だけmissing sourceをunavailable化
- 現行incremental実装はlatest側から異なるknown source 2件連続で停止し、同一stable identityの重複観測はstreakに加算しない
- 採用仕様ではdefault known-streakを維持しつつ、site固有access遷移に必要なstable boundary hookを許容する。BookWalker Discoveryはこのhookを利用する
- 別site同一作品は自動mergeせずwarning only
- access modeは `owned / free / quota / paid / unknown`
- quotaは基本crawl開始時に消費記録
- site上に再閲覧猶予がある場合は `access_granted_until` で扱える。BookWalkerはsource単位grantを仮定しない採用仕様
- Batch/Site Policyが今回の `access_strategy` を解決する
- quota sourceでもactive grant中は `direct`、新規枠を使う場合だけ `quota`
- quota limit/reset ruleそのものをCrawlerへ渡さない
- Crawlerはtitle/author/order/genreをoptional inputとして受け取れるようにする
- metadataはfield単位で `explicit request > adapter > packaging fallback`
- metadata未指定なら現行Adapter自動取得を維持する
- crawl + packaging成功時だけArtifact(present)、CrawlRun(succeeded)、Item(completed)を1 transactionで確定

Phase 5AのBatch Plannerは `pending` itemだけを対象にし、completed / unavailable / paid / unknownをskipする。source priorityは期限付きfree、通常free、owned、quota、paid/unknownの順で、同順位はsource.id ASC。複数のquota-consuming candidateが新規枠を必要とする場合、quota仮予約の順序は`source.discovery_key`ごとのDiscovery groupをgroup内最小source.id（Catalog登録順）で並べ、group内を`order_key`のnatural orderで並べる。`order_key`を解釈できない場合は`order_label`、最後にitem.idのstable fallbackを使う。`discovery_key = NULL`のcandidateは明示groupの後ろに置く。free、owned、active grant中のquota sourceはdirectのままでこのquota allocation順序に入らない。Catalog metadataは`canonical_title -> title`、`author -> author`、`order_label -> order`、`genre -> genre`でcandidateへ写し、NULL/空値は省略する。

Manga ONE Policyはsite-wide local quotaを4枠、09:00/21:00 JSTのhalf-open window、24時間grantとして扱う。current window内の`quota_started_at`だけを数え、active grant（`access_granted_until > now`）はdirectでslotを減らさない。quota candidateはplanner内だけで仮予約し、Catalogは変更しない。手動・外部clientの実消費はCatalogから観測できない。

CLIは `batch plan --site mangaone --catalog catalog.sqlite` と `batch run --site mangaone --catalog catalog.sqlite` を提供する。`batch plan`はread-onlyで、`batch run`はcandidateをsequentialに実行し、quota stateをCrawler開始直前に保存し、crawl + packaging成功後だけcompletedを更新する。`--limit N`は先頭N件に制限し、失敗時は後続を実行しない。

BookWalker Discoveryはseries listから商品URLを列挙し、商品ページのreader controlを観測してCatalogへ反映する。BookWalker Site Policyはsite-wide 1 quota / 05:00 JST half-open windowを評価し、`access_granted_until`をdirect判定に使わない。Batch Executorはquota candidateの`quota_started_at`をCrawler開始前に保存し、`access_granted_until=NULL`を許容する。同一window内の失敗はrefundせず、Executorの現在Catalog再検証で同一candidateをCrawlerへ再投入しない。Manga ONEの24時間grant挙動は維持する。実サイトquota clickは自動検証していない。

### 22.3 Discovery framework（実装済み）

`DiscoveryService`（`src/screenshot_crawler/discovery/`）は、呼び出し元が用意したPlaywright Page、enabledな`WatchlistTarget`、`full`または`incremental` modeを受け取る。Chrome launch、CDP endpoint、profile、Browser Session lifecycleはServiceやDiscovery Adapterに持たせない。targetの`work_key`でWorkをfind/createし、Work titleは新規作成時だけ`label`から初期化する。author/genreは観測値が非NULLでWork側がNULLの場合だけ補完し、既存値を上書きしない。

`DiscoveryAdapter.iter_records()`はsite-neutralな`DiscoveredRecord`を順次yieldする。AdapterはCatalogを知らず、`site`と`discovery_key`はServiceがtargetからCatalogへ注入する。現行のreal-site用AdapterはManga ONEとBookWalkerである。BookWalkerはWatchlistのseries list targetだけを対象にする。

Discovery Serviceは各recordについて、canonical titleをItemへ保存せず、kind/orderをItemへ、title/author/genreをWorkへ反映する。新規recordではItem/Source/web-default targetを一つのtransactionで作成し、既存sourceでは既存Itemを再利用して外部状態と非NULL Item metadataだけを更新する。観測した`DiscoveredSource.url`は`SourceTargetInput(backend="web", target_key="default", locator=...)`として同じsourceへupsertする。URL変更は同じ`(source_id, web, default)` targetのlocator更新になり、既存androidやweb/direct等の別targetは変更しない。sourceのfull-sync missing reconciliationは`available=false`だけを更新し、targetの削除や自動disableは行わない。既存sourceの`discovery_key` scope不一致、または既存Itemが別Workに属する場合はincompleteとして扱い、reparentや部分的な新規graph作成を行わない。

Discovery開始時、Serviceは対象siteの既存sourceからCatalog非依存の
`DiscoverySourceSnapshot`を一度だけ作成し、adapter hookへ渡す。このsnapshotはrun開始時点をauthorityとし、run中に新規upsertされたsourceを既存sourceとして扱わない。
`DiscoveryAdapter.reconcile_access_mode()`は観測したaccess modeだけをsite-specificに調整でき、defaultは観測値をそのまま返す。`incremental_stop_decision()`は
`DEFAULT` / `CONTINUE` / `STOP`を返し、defaultでは従来のknown source 2件連続停止を使う。`STOP`はrecordのupsert後に`stable_boundary`で終了し、full modeではstop hookを呼ばない。両hookからの`DiscoveryIncompleteError`は既存のincomplete semanticsに従う。

fullはiteratorの正常終了だけを`complete=true`とし、`DiscoveryIncompleteError`または予期しない例外ではmissing sourceのreconciliationを行わない。complete fullだけが同じ`site + discovery_key` scopeの未観測sourceを`available=false`にする。現行incrementalのknown判定と2件連続streakはServiceが管理し、2件目をrefreshしてから停止する。未観測sourceはunavailableにしない。

BookWalkerはこのextension pointを実装し、run開始時点でowned/quotaだったsourceをstable boundaryとして扱う。既存owned/quotaのaccess stateは、商品ページの観測がpaid/unknownへ揺れた場合も保持する。Manga ONEはhookをoverrideせず、従来のknown-streak挙動を使う。

### 22.4 Discovery CLIの複数target同期（実装済み）

`discover` は `--key KEY` と `--all` のmutually exclusive required groupを持つ。
`--key` は従来どおり1 targetを処理し、`--all` は
`WatchlistService.list_targets()` のfile orderから `target.enabled is True`
のtargetだけを選ぶ。disabled targetはDiscoveryServiceへ渡さないため、Catalogの
既存stateは変更されない。enabled targetが0件なら接続せず、
`No enabled watchlist targets.`を出して正常終了する。

`--all`ではtargetごとにendpointを解決し、`BrowserSession.connect()`、new Page、
既存`DiscoveryService.discover(page, target, mode)`、Page close、disconnectを
順番に行う。site-specific endpoint、global endpoint、defaultの既存優先順位と、
明示`--cdp-endpoint`の最優先を維持する。Crawler Chromeは自動起動しない。

各targetの結果（observed/new/known/complete/stopped_reason/warnings）とstatusを
表示し、失敗しても後続targetを続行する。例外failureに加えて
`DiscoveryResult.stopped_reason == "incomplete"`もtarget failureとして扱い、
`Discovery incomplete`を表示する。全target後にsummaryを表示し、1件以上の失敗は
`DiscoveryAllError`からCLI non-zeroへ変換する。全成功とenabled target 0件は正常終了
する。`--all --keep-open`はtarget単位で接続を閉じるlifecycleのためCLI validationで
拒否し、従来の`--key --keep-open`だけを維持する。

cross-site duplicateは同じWork内の別Itemについて、kind/orderが一致する場合だけ候補をwarningにする。warningはmerge、reparent、delete、completed化を行わない。

### 22.5 Batch Planner / Executor（Schema v3 Phase 3実装済み）

`BatchPlanner`（`src/screenshot_crawler/batch/planner.py`）はWork-aware read snapshotから
candidateを生成する。metadataは`Work.title` / `Work.author` / `Work.genre` / `Item.order_label`
から作り、Itemのorder fallbackは`order_key`、`order_label`、`item_title`、`item.id`の順である。
指定siteのSourceを持つItemだけを対象にし、Web targetだけを`priority ASC, target.id ASC`
で選ぶ。`BatchCandidate`には`backend` / `target_key` / `locator`をsnapshotする。

`BatchExecutor`（`src/screenshot_crawler/batch/executor.py`）はcandidateを1件ずつ既存
`CrawlerRunner`へ渡す。`CrawlerRunner`はCatalogを知らず、Batch側だけが`item_id` /
`source_id` / `target_id`とCatalog stateを扱う。

実行前にitemが`pending`であり、sourceのitem/site/access_mode/availableとtargetの
source/backend/target_key/locator/enabledがcandidateと一致することを確認する。backendはwebだけを
受け付ける。Policyのaccess decisionも再確認し、stale candidateはCrawlerを呼ばずに停止する。

Candidateから次の`RunConfig`を作る:

```text
site / source_url / access_strategy / output_metadata
output_dir = output/batch/<site>/item-<item>-source-<source>-<JST timestamp>-<uuid>
diagnostics_dir = <run directory>/diagnostics
```

実行はsequential、stop-on-first-failureである。candidate validation後、Crawler開始前に
`CrawlRun(running)`を作成する。quota candidateだけはその後に`record_quota_access()`を呼び、
Policyの`access_grant_until()`で計算したgrantを保存する。direct candidateはquota stateを
変更しない。保存後にcrawl、viewer、packagingが失敗してもquota stateはrefundしない。

Crawlerが`END`または`NEXT_CONTENT`で正常終了し、既存`package_crawl_output()`が成功した後、
archiveの存在を確認してSHA-256 / byte sizeを計算する。Catalogのnarrow helperがArtifact(present)、
CrawlRun(succeeded)、Item(completed)を1 transactionで確定する。Catalog更新失敗時も生成済みarchiveと
status sidecarは削除しない。Crawler、異常停止、packaging、archive検証、finalizeの失敗は
CrawlRun(failed)へ記録し、Itemはpending、Artifactは作成しない。

実行CLI:

```powershell
.\.venv\Scripts\python.exe -m screenshot_crawler.cli batch run `
  --site mangaone --catalog catalog.sqlite `
  --output-root output\batch --library-dir output\Books --limit 1
```

`batch plan`は引き続きCatalog read-onlyであり、`batch run`だけがquota local stateと
CrawlRun / Artifact / Item statusを書き換える。Manga ONEとBookWalkerのquota policyは既存挙動を
維持し、Android targetはCatalogへ保持できるがPhase 3 Executorでは実行しない。
